"""Integration Hub Celery consumers — inbound webhooks and outbound adapter calls."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID

import httpx
from loguru import logger

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import async_session_factory, run_celery_async
from app.models.integration_hub import (
    AgentActionStatus,
    IntegrationConnection,
    WebhookEventStatus,
)
from app.services.integration_hub.amocrm_account import AmoCRMAccountRateLimited
from app.services.integration_hub.bitrix_portal import BitrixPortalRateLimited
from app.services.integration_hub.crm_adapter import get_crm_adapter
from app.services.integration_hub.hub_usage import (
    build_hub_action_idempotency_key,
    record_hub_usage,
)
from app.services.integration_hub.oauth import secrets_from_connection_with_vault
from app.services.integration_hub.queue import (
    CRM_ADAPTER_ACTIONS,
    MAX_RETRIES,
    MESSAGING_ADAPTER_ACTIONS,
    PAYMENT_ADAPTER_ACTIONS,
    OutboundConnectionBusy,
    assert_connection_allows_outbound,
    canonical_action_type,
    claim_webhook_event,
    mark_webhook_event,
    normalize_hub_event,
    outbound_job_timeout_seconds,
    persist_agent_action,
    release_outbound_lock,
    reset_webhook_event_for_retry,
    serialize_action_result,
    try_acquire_outbound_lock,
    webhook_retry_countdown,
)
from app.services.integration_hub.rate_limit import ConnectionRateLimited


def _hub_webhook_max_retries() -> int:
    return max(0, int(getattr(settings, "HUB_WEBHOOK_MAX_RETRIES", MAX_RETRIES) or MAX_RETRIES))


@celery_app.task(
    bind=True,
    name="app.tasks.hub_queue_tasks.process_hub_webhook_event",
    max_retries=8,
    acks_late=True,
)
def process_hub_webhook_event_task(self, event_id: str) -> dict[str, Any]:
    max_retries = _hub_webhook_max_retries()
    try:
        return run_celery_async(_consume_webhook_event(event_id))
    except (BitrixPortalRateLimited, AmoCRMAccountRateLimited, ConnectionRateLimited) as exc:
        raise self.retry(exc=exc, countdown=min(60, 2 ** int(self.request.retries or 0))) from exc
    except Exception as exc:
        attempt = int(self.request.retries or 0)
        if attempt >= max_retries:
            run_celery_async(
                _dead_letter_webhook(event_id, f"max_retries={max_retries}: {exc}")
            )
            logger.error(
                "HubQueue.webhook_dead_letter | event_id={eid} retries={n} error={error}",
                eid=event_id,
                n=attempt,
                error=str(exc),
            )
            return {"status": "dead_letter", "event_id": event_id}
        countdown = webhook_retry_countdown(attempt + 1)
        run_celery_async(_requeue_webhook(event_id, str(exc), countdown=countdown))
        raise self.retry(
            exc=exc,
            countdown=countdown,
            max_retries=max_retries,
        ) from exc


@celery_app.task(
    bind=True,
    name="app.tasks.hub_queue_tasks.execute_hub_adapter_action",
    max_retries=12,
    acks_late=True,
)
def execute_hub_adapter_action_task(
    self,
    connection_id: str,
    action_type: str,
    params: dict[str, Any] | None = None,
) -> Any:
    if not try_acquire_outbound_lock(connection_id):
        raise self.retry(
            exc=OutboundConnectionBusy(f"Outbound in flight for {connection_id}"),
            countdown=1,
        )
    task_id = str(getattr(self.request, "id", None) or "") or None
    try:
        return run_celery_async(
            _execute_adapter_action_bounded(
                connection_id,
                action_type,
                params or {},
                celery_task_id=task_id,
            )
        )
    except (BitrixPortalRateLimited, AmoCRMAccountRateLimited, ConnectionRateLimited) as exc:
        raise self.retry(exc=exc, countdown=min(30, 1 + int(self.request.retries or 0))) from exc
    finally:
        # Successful release; kill -9 skips this and Redis EX TTL frees the key.
        release_outbound_lock(connection_id)


async def _execute_adapter_action_bounded(
    connection_id: str,
    action_type: str,
    params: dict[str, Any],
    *,
    celery_task_id: str | None = None,
) -> Any:
    """Soft timeout strictly below ``HUB_OUTBOUND_LOCK_TTL_SECONDS``."""
    timeout = outbound_job_timeout_seconds()
    try:
        return await asyncio.wait_for(
            _execute_adapter_action(
                connection_id,
                action_type,
                params,
                celery_task_id=celery_task_id,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        logger.error(
            "HubQueue.outbound_soft_timeout | connection_id={id} action={action} "
            "timeout_s={timeout}",
            id=connection_id,
            action=action_type,
            timeout=timeout,
        )
        raise TimeoutError(
            f"Hub outbound job exceeded soft timeout ({timeout}s); "
            "Redis lock TTL will reclaim connection_id if the worker dies"
        ) from exc


async def _dead_letter_webhook(event_id: str, error: str) -> None:
    from app.services.integration_hub.alerts import send_alert_to_monitoring

    async with async_session_factory() as db:
        await mark_webhook_event(
            db,
            UUID(event_id),
            status=WebhookEventStatus.DEAD_LETTER.value,
            error=error,
        )
        await db.commit()
    send_alert_to_monitoring(
        severity="critical",
        title="Integration Hub webhook dead_letter",
        details={"event_id": event_id, "error": error[:500]},
    )


async def _requeue_webhook(
    event_id: str,
    error: str,
    *,
    countdown: int | None = None,
) -> None:
    async with async_session_factory() as db:
        await reset_webhook_event_for_retry(
            db,
            UUID(event_id),
            error=error,
            countdown=countdown,
        )
        await db.commit()


async def _consume_webhook_event(event_id: str) -> dict[str, Any]:
    eid = UUID(event_id)
    async with async_session_factory() as db:
        outcome, event = await claim_webhook_event(db, eid)
        if outcome != "claimed" or event is None:
            await db.commit()
            return {"status": outcome, "event_id": event_id}
        connection = (
            await db.get(IntegrationConnection, event.connection_id)
            if event.connection_id
            else None
        )
        if connection is None:
            await mark_webhook_event(
                db,
                eid,
                status=WebhookEventStatus.DEAD_LETTER.value,
                error="connection_missing",
            )
            await db.commit()
            return {"status": "missing_connection", "event_id": event_id}
        # Tenant binding: event.organization_id must match the connection workspace.
        if event.organization_id and event.organization_id != connection.organization_id:
            await mark_webhook_event(
                db,
                eid,
                status=WebhookEventStatus.DEAD_LETTER.value,
                error="workspace_mismatch",
            )
            await db.commit()
            return {"status": "workspace_mismatch", "event_id": event_id}
        # Also reject forged workspace_id inside the payload.
        from app.services.integration_hub.webhook_dedup import extract_payload_workspace_id

        payload_preview = dict(event.payload_json or {})
        hinted = extract_payload_workspace_id(payload_preview)
        if hinted is not None and hinted != connection.organization_id:
            await mark_webhook_event(
                db,
                eid,
                status=WebhookEventStatus.DEAD_LETTER.value,
                error="workspace_mismatch",
            )
            await db.commit()
            return {"status": "workspace_mismatch", "event_id": event_id}
        normalized = normalize_hub_event(event=event, connection=connection)
        payload = payload_preview
        provider = event.provider
        connection_id = str(connection.id)
        await db.commit()

    # Failures bubble to the task wrapper for retry / dead_letter — do not mark ERROR here
    # (ERROR previously blocked Celery retries because claim only accepted received).
    dispatched = await _dispatch_normalized(
        provider=provider,
        connection_id=connection_id,
        normalized=normalized,
        payload=payload,
    )

    async with async_session_factory() as db:
        await mark_webhook_event(db, eid, status=WebhookEventStatus.PROCESSED.value)
        await db.commit()
    logger.info(
        "HubQueue.webhook_processed | event_id={eid} provider={provider} "
        "workspace_id={ws} agent_id={agent} type={type}",
        eid=event_id,
        provider=provider,
        ws=normalized.get("workspace_id"),
        agent=normalized.get("agent_id"),
        type=normalized.get("type"),
    )
    return {"status": "processed", "event_id": event_id, **dispatched}


async def _dispatch_normalized(
    *,
    provider: str,
    connection_id: str,
    normalized: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    event_type = str(normalized.get("type") or "")
    if provider == "wazzup" or event_type == "message.received":
        from app.tasks.wazzup_tasks import _process

        result = await _process(connection_id, [payload])
        return {"runtime": "ai_agent", **result}

    if provider == "bitrix24":
        from app.services.integration_hub.adapters.bitrix24 import parse_bitrix_webhook
        from app.tasks.bitrix24_tasks import _process_event

        parsed = parse_bitrix_webhook(payload)
        result = await _process_event(
            connection_id,
            str(parsed.get("event") or payload.get("event") or ""),
            payload,
        )
        return {"runtime": "crm", **result}

    if provider in {"amocrm", "kommo"}:
        from app.tasks.amocrm_tasks import _process_event

        result = await _process_event(connection_id, payload)
        return {"runtime": "crm", **result}

    if provider == "kaspi_pay" or event_type.startswith("payment."):
        from app.tasks.kaspi_tasks import _process_event

        result = await _process_event(connection_id, payload)
        return {"runtime": "payments", **result}

    logger.info(
        "HubQueue.unhandled_provider | provider={provider} connection_id={id}",
        provider=provider,
        id=connection_id,
    )
    return {"runtime": "none"}


def _hub_adapter_metric(*, provider: str, action: str) -> str:
    if action == "send_message":
        return "wazzup_outbound"
    if provider == "bitrix24":
        return "bitrix24_rest"
    if provider in {"amocrm", "kommo"}:
        return "amocrm_rest"
    if provider == "kaspi_pay":
        return "kaspi_pay_invoice"
    return "hub_adapter_ok"


async def _execute_adapter_action(
    connection_id: str,
    action_type: str,
    params: dict[str, Any],
    *,
    celery_task_id: str | None = None,
) -> Any:
    started = time.perf_counter()
    async with async_session_factory() as db:
        connection = await assert_connection_allows_outbound(db, connection_id)
        secrets = await secrets_from_connection_with_vault(db, connection)
        action = canonical_action_type(action_type)
        status = AgentActionStatus.OK.value
        error: str | None = None
        result: Any = None
        response: dict[str, Any] = {}
        action_id = params.get("action_id") or params.get("idempotency_key")
        event_id = params.get("event_id")
        usage_key = build_hub_action_idempotency_key(
            connection_id=connection.id,
            action_type=action,
            action_id=str(action_id) if action_id else None,
            event_id=str(event_id) if event_id else None,
            task_id=celery_task_id,
        )
        try:
            async with httpx.AsyncClient(timeout=20.0) as http:
                result = await _call_adapter(
                    connection=connection,
                    action_type=action,
                    params=params,
                    secrets=secrets,
                    http=http,
                )
            response = serialize_action_result(result)
            await record_hub_usage(
                db,
                connection=connection,
                metric=_hub_adapter_metric(provider=connection.provider, action=action),
                quantity=1,
                idempotency_key=usage_key,
                meta={
                    "action_type": action,
                    "action_id": str(action_id) if action_id else None,
                    "event_id": str(event_id) if event_id else None,
                },
            )
        except (BitrixPortalRateLimited, AmoCRMAccountRateLimited, ConnectionRateLimited):
            status = AgentActionStatus.RATE_LIMITED.value
            error = "rate_limited"
            duration_ms = int((time.perf_counter() - started) * 1000)
            await persist_agent_action(
                db,
                connection=connection,
                action_type=action,
                request_payload=params,
                response_payload={},
                status=status,
                error=error,
                duration_ms=duration_ms,
            )
            await db.commit()
            raise
        except Exception as exc:
            status = AgentActionStatus.ERROR.value
            error = str(exc)
            raise
        finally:
            if status != AgentActionStatus.RATE_LIMITED.value:
                duration_ms = int((time.perf_counter() - started) * 1000)
                external_id = None
                if isinstance(response, dict) and response.get("id"):
                    external_id = str(response.get("id"))
                await persist_agent_action(
                    db,
                    connection=connection,
                    action_type=action,
                    request_payload=params,
                    response_payload=response,
                    status=status,
                    error=error,
                    duration_ms=duration_ms,
                    external_id=external_id,
                )
                await db.commit()
        return result


async def _call_adapter(
    *,
    connection: IntegrationConnection,
    action_type: str,
    params: dict[str, Any],
    secrets: Any,
    http: httpx.AsyncClient,
) -> Any:
    action = canonical_action_type(action_type)
    kwargs = dict(params or {})
    kwargs.pop("secrets", None)
    kwargs.pop("http", None)
    kwargs.pop("connection_id", None)
    kwargs.pop("action_id", None)
    kwargs.pop("event_id", None)
    kwargs.pop("idempotency_key", None)
    if action in CRM_ADAPTER_ACTIONS:
        adapter = get_crm_adapter(connection.provider)
        if adapter is None:
            raise ValueError(f"No CRM adapter for provider {connection.provider}")
        method = getattr(adapter, action, None)
        if method is None:
            raise ValueError(f"Adapter {connection.provider} has no {action}")
        return await method(
            secrets=secrets,
            http=http,
            connection_id=connection.id,
            **kwargs,
        )
    if action in MESSAGING_ADAPTER_ACTIONS:
        if connection.provider != "wazzup":
            raise ValueError("send_message is only supported via Wazzup")
        from app.services.integration_hub.adapters.wazzup import WazzupHubAdapter

        return await WazzupHubAdapter().send_message(
            secrets=secrets,
            http=http,
            connection_id=connection.id,
            **kwargs,
        )
    if action in PAYMENT_ADAPTER_ACTIONS:
        if connection.provider != "kaspi_pay":
            raise ValueError("create_invoice is only supported via Kaspi Pay")
        from app.services.integration_hub.adapters.kaspi import KaspiPayHubAdapter

        return await KaspiPayHubAdapter().create_invoice(
            secrets=secrets,
            http=http,
            connection_id=connection.id,
            **kwargs,
        )
    raise ValueError(f"Unknown hub adapter action: {action}")
