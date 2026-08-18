"""Isolated Celery workers for CRM pipeline automation."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
from celery.exceptions import MaxRetriesExceededError
from loguru import logger
from pydantic import ValidationError

from app.core.celery_app import celery_app
from app.core.database import async_session_factory
from app.models.core_models import DiagnosticErrorType
from app.schemas.crm_schemas import CRMActionPayload, CRMAutomationTaskPayload
from app.services.crm_orchestrator import CRMTransientError, crm_orchestrator
from app.services.diagnostic_log_service import diagnostic_log_service

CRM_MAX_RETRIES = 3
CRM_RETRY_COUNTDOWN_SECONDS = 60

RETRIABLE_EXCEPTIONS = (
    CRMTransientError,
    ConnectionError,
    TimeoutError,
    OSError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.TransportError,
)


async def _persist_crm_disconnect(
    *,
    bot_id: uuid.UUID,
    session_id: uuid.UUID | None,
    error_message: str,
    node_id: str | None,
) -> None:
    async with async_session_factory() as db:
        try:
            await diagnostic_log_service.log(
                db,
                bot_id=bot_id,
                client_id=session_id,
                error_type=DiagnosticErrorType.CRM_DISCONNECT,
                error_message=error_message,
                node_id=node_id,
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception(
                "CRMWorker.diagnostic_log_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )


def _validate_action_data(action_data: dict[str, Any]) -> dict[str, Any]:
    try:
        return CRMActionPayload.model_validate(action_data).model_dump(mode="json")
    except ValidationError as exc:
        raise ValueError(f"Invalid CRM action payload: {exc}") from exc


def _run_crm_automation(
    *,
    bot_id: str,
    session_id: str,
    action_data: dict[str, Any],
    task_id: str | None,
    retries: int,
    retry_callback: Any,
) -> dict[str, Any]:
    logger.info(
        "CRMWorker.received | task_id={task_id} bot_id={bot_id} session_id={session_id} retries={retries}",
        task_id=task_id,
        bot_id=bot_id,
        session_id=session_id,
        retries=retries,
    )

    try:
        envelope = CRMAutomationTaskPayload.model_validate(
            {
                "bot_id": bot_id,
                "session_id": session_id,
                "action_data": action_data,
            }
        )
        validated_action = _validate_action_data(envelope.action_data)
    except (ValidationError, ValueError) as exc:
        logger.error(
            "CRMWorker.invalid_payload | bot_id={bot_id} session_id={session_id} error={error}",
            bot_id=bot_id,
            session_id=session_id,
            error=str(exc),
        )
        return {"success": False, "error": str(exc), "retriable": False}

    node_id = str(validated_action.get("node_id") or "") or None

    try:
        result = asyncio.run(
            crm_orchestrator.execute_crm_action(
                envelope.bot_id,
                envelope.session_id,
                validated_action,
            )
        )
        logger.info(
            "CRMWorker.complete | task_id={task_id} bot_id={bot_id} session_id={session_id} success={success}",
            task_id=task_id,
            bot_id=bot_id,
            session_id=session_id,
            success=result.get("success"),
        )
        return result
    except RETRIABLE_EXCEPTIONS as exc:
        logger.warning(
            "CRMWorker.retryable | task_id={task_id} bot_id={bot_id} session_id={session_id} "
            "error={error} attempt={attempt}",
            task_id=task_id,
            bot_id=bot_id,
            session_id=session_id,
            error=str(exc),
            attempt=retries + 1,
        )
        try:
            raise retry_callback(exc)
        except MaxRetriesExceededError:
            asyncio.run(
                _persist_crm_disconnect(
                    bot_id=envelope.bot_id,
                    session_id=envelope.session_id,
                    error_message=f"CRM automation exhausted retries: {exc}",
                    node_id=node_id,
                )
            )
            return {
                "success": False,
                "error": str(exc),
                "retriable": False,
                "retries_exhausted": True,
            }
    except Exception as exc:
        logger.exception(
            "CRMWorker.failed | task_id={task_id} bot_id={bot_id} session_id={session_id} error={error}",
            task_id=task_id,
            bot_id=bot_id,
            session_id=session_id,
            error=str(exc),
        )
        asyncio.run(
            _persist_crm_disconnect(
                bot_id=envelope.bot_id,
                session_id=envelope.session_id,
                error_message=str(exc),
                node_id=node_id,
            )
        )
        return {"success": False, "error": str(exc), "retriable": False}


@celery_app.task(
    bind=True,
    name="app.workers.crm_tasks.process_crm_automation_action",
    max_retries=CRM_MAX_RETRIES,
    autoretry_for=RETRIABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def process_crm_automation_action(
    self,
    bot_id: str,
    session_id: str,
    action_data: dict[str, Any],
) -> dict[str, Any]:
    """Background CRM pipeline worker.

    Loads active CRM credentials (``sync_enabled=True``) for ``bot_id`` and executes
    contact deduplication + lead provisioning without blocking the API event loop.
    ``session_id`` maps to the platform ``Client.id`` conversation ledger.
    """
    return _run_crm_automation(
        bot_id=bot_id,
        session_id=session_id,
        action_data=action_data,
        task_id=self.request.id,
        retries=self.request.retries,
        retry_callback=lambda exc: self.retry(exc=exc, countdown=CRM_RETRY_COUNTDOWN_SECONDS),
    )


@celery_app.task(
    bind=True,
    name="app.tasks.crm_tasks.process_crm_action_task",
    max_retries=CRM_MAX_RETRIES,
    autoretry_for=RETRIABLE_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def process_crm_action_task(
    self,
    bot_id: str,
    client_id: str,
    action_data: dict[str, Any],
) -> dict[str, Any]:
    """Legacy alias — ``client_id`` is treated as the CRM session ledger id."""
    return _run_crm_automation(
        bot_id=bot_id,
        session_id=client_id,
        action_data=action_data,
        task_id=self.request.id,
        retries=self.request.retries,
        retry_callback=lambda exc: self.retry(exc=exc, countdown=CRM_RETRY_COUNTDOWN_SECONDS),
    )


async def _capture_lead_async(client_id: uuid.UUID, bot_id: uuid.UUID) -> dict[str, Any]:
    """Create CRM contact (+ deal on first capture) when auto-capture is enabled."""
    from app.models.core_models import Bot
    from app.repositories.crm.contact_repository import contact_repository
    from app.repositories.crm.pipeline_repository import pipeline_repository
    from app.schemas.crm.deals import CrmDealCreate
    from app.services.crm.contact_service import ContactServiceError, contact_service
    from app.services.crm.deal_service import DealServiceError, deal_service
    from app.services.crm.setting_service import setting_service
    from app.services.crm.timeline_service import timeline_service
    from sqlalchemy import select

    async with async_session_factory() as db:
        try:
            bot = await db.scalar(select(Bot).where(Bot.id == bot_id))
            if bot is None or bot.organization_id is None:
                logger.warning(
                    "CRM.capture_skip | reason=no_bot_or_org bot_id={bot_id} client_id={client_id}",
                    bot_id=bot_id,
                    client_id=client_id,
                )
                return {"success": False, "skipped": True, "reason": "no_bot_or_org"}

            organization_id = uuid.UUID(str(bot.organization_id))
            settings_row = await setting_service.get(db, organization_id)
            if not settings_row.auto_capture_enabled:
                logger.info(
                    "CRM.capture_disabled | organization_id={organization_id} client_id={client_id}",
                    organization_id=organization_id,
                    client_id=client_id,
                )
                return {"success": True, "skipped": True, "reason": "auto_capture_disabled"}

            contacts = contact_repository(db, organization_id=organization_id)
            existed = await contacts.get_by_linked_client_id(client_id)
            contact_was_new = existed is None

            try:
                contact = await contact_service.get_or_create_from_client(db, client_id)
            except ContactServiceError as exc:
                logger.warning(
                    "CRM.capture_contact_failed | client_id={client_id} error={error}",
                    client_id=client_id,
                    error=exc.message,
                )
                return {"success": False, "error": exc.message}

            if not contact_was_new:
                await db.commit()
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "contact_already_exists",
                    "contact_id": str(contact.id),
                }

            pipelines = pipeline_repository(db, organization_id=organization_id)
            pipeline = await pipelines.get_default()
            if pipeline is None:
                listed = await pipelines.list_with_stages(limit=1)
                pipeline = listed[0] if listed else None
            if pipeline is None or not pipeline.stages:
                logger.warning(
                    "CRM.capture_no_pipeline | organization_id={organization_id} client_id={client_id}",
                    organization_id=organization_id,
                    client_id=client_id,
                )
                await db.commit()
                return {
                    "success": True,
                    "contact_id": str(contact.id),
                    "deal_created": False,
                    "reason": "no_default_pipeline",
                }

            first_stage = sorted(pipeline.stages, key=lambda s: s.position)[0]
            display_name = (contact.first_name or "").strip() or "Lead"
            source = contact.source
            try:
                deal = await deal_service.create_deal(
                    db,
                    organization_id,
                    CrmDealCreate(
                        title=f"Deal: {display_name}",
                        pipeline_id=pipeline.id,
                        stage_id=first_stage.id,
                        contact_id=contact.id,
                        bot_id=bot_id,
                        source=source,
                    ),
                )
            except DealServiceError as exc:
                logger.warning(
                    "CRM.capture_deal_failed | client_id={client_id} error={error}",
                    client_id=client_id,
                    error=exc.message,
                )
                await db.commit()
                return {
                    "success": False,
                    "contact_id": str(contact.id),
                    "error": exc.message,
                }

            await timeline_service.log_event(
                db,
                organization_id,
                event_type="lead_captured",
                deal_id=deal.id,
                contact_id=contact.id,
                payload={
                    "client_id": str(client_id),
                    "bot_id": str(bot_id),
                    "source": source,
                },
            )
            await db.commit()
            logger.info(
                "CRM.lead_captured | deal_id={deal_id} contact_id={contact_id} client_id={client_id}",
                deal_id=deal.id,
                contact_id=contact.id,
                client_id=client_id,
            )
            return {
                "success": True,
                "contact_id": str(contact.id),
                "deal_id": str(deal.id),
                "deal_created": True,
            }
        except Exception:
            await db.rollback()
            raise


@celery_app.task(
    bind=True,
    name="app.tasks.crm_tasks.capture_lead_task",
    max_retries=3,
    soft_time_limit=60,
)
def capture_lead_task(self, client_id_str: str, bot_id_str: str) -> dict[str, Any]:
    """Auto-capture inbox Client → CrmContact (+ deal) on the ``crm_actions`` queue."""
    from app.config import settings

    logger.info(
        "CRM.capture_lead_task | task_id={task_id} client_id={client_id} bot_id={bot_id} queue={queue}",
        task_id=self.request.id,
        client_id=client_id_str,
        bot_id=bot_id_str,
        queue=settings.CELERY_CRM_QUEUE,
    )
    try:
        return asyncio.run(
            _capture_lead_async(uuid.UUID(client_id_str), uuid.UUID(bot_id_str))
        )
    except Exception as exc:
        logger.exception(
            "CRM.capture_lead_failed | client_id={client_id} bot_id={bot_id} error={error}",
            client_id=client_id_str,
            bot_id=bot_id_str,
            error=str(exc),
        )
        raise


async def _run_automation_async(
    organization_id: uuid.UUID,
    deal_id: uuid.UUID,
    trigger_type_value: str,
    context_extra: dict[str, Any] | None,
) -> dict[str, Any]:
    from app.models.crm.automation_rule import AutomationTriggerType
    from app.repositories.crm.deal_repository import deal_repository
    from app.services.crm.automation_executor_service import automation_executor_service

    trigger_type = AutomationTriggerType(trigger_type_value)
    async with async_session_factory() as db:
        try:
            deal = await deal_repository(db, organization_id=organization_id).get_with_relations(
                deal_id
            )
            if deal is None:
                logger.warning(
                    "CRM.run_automation_skip | reason=deal_not_found deal_id={deal_id} org={org}",
                    deal_id=deal_id,
                    org=organization_id,
                )
                return {"success": False, "skipped": True, "reason": "deal_not_found"}
            results = await automation_executor_service.run_triggers(
                db,
                trigger_type,
                deal,
                context_extra=context_extra,
            )
            await db.commit()
            return {
                "success": True,
                "deal_id": str(deal_id),
                "trigger_type": trigger_type.value,
                "results": results,
            }
        except Exception:
            await db.rollback()
            raise


@celery_app.task(
    bind=True,
    name="app.tasks.crm_tasks.run_automation_task",
    max_retries=3,
    soft_time_limit=120,
)
def run_automation_task(
    self,
    organization_id_str: str,
    deal_id_str: str,
    trigger_type: str,
    context_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply active CRM automation rules for a deal event (queue: ``crm_actions``)."""
    from app.config import settings

    logger.info(
        "CRM.run_automation_task | task_id={task_id} deal_id={deal_id} trigger={trigger} queue={queue}",
        task_id=self.request.id,
        deal_id=deal_id_str,
        trigger=trigger_type,
        queue=settings.CELERY_CRM_QUEUE,
    )
    try:
        return asyncio.run(
            _run_automation_async(
                uuid.UUID(organization_id_str),
                uuid.UUID(deal_id_str),
                trigger_type,
                context_extra or {},
            )
        )
    except Exception as exc:
        logger.exception(
            "CRM.run_automation_failed | deal_id={deal_id} trigger={trigger} error={error}",
            deal_id=deal_id_str,
            trigger=trigger_type,
            error=str(exc),
        )
        raise