"""CRM deal service — CRUD, move_stage, close_deal."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.automation_rule import AutomationTriggerType
from app.models.crm.deal import CrmDeal, DealStatus
from app.repositories.crm.account_repository import account_repository
from app.repositories.crm.contact_repository import contact_repository
from app.repositories.crm.deal_repository import deal_repository
from app.repositories.crm.pipeline_repository import pipeline_repository
from app.repositories.crm.stage_repository import stage_repository
from app.schemas.crm.deals import (
    CrmDealCloseRequest,
    CrmDealCreate,
    CrmDealListResponse,
    CrmDealRead,
    CrmDealUpdate,
)
from app.services.crm.deal_access import CrmActor


class DealServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DealService:
    def _deals(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        actor: CrmActor | None = None,
    ):
        viewer_user_id = None
        viewer_role = None
        if actor is not None and not actor.sees_all_deals:
            viewer_user_id = actor.user_id
            viewer_role = actor.role
        return deal_repository(
            db,
            organization_id=organization_id,
            viewer_user_id=viewer_user_id,
            viewer_role=viewer_role,
        )

    def _deals_unscoped(self, db: AsyncSession, organization_id: uuid.UUID):
        # Same factory as scoped reads with actor=None → full tenant visibility.
        return self._deals(db, organization_id, actor=None)

    def _pipelines(self, db: AsyncSession, organization_id: uuid.UUID):
        return pipeline_repository(db, organization_id=organization_id)

    def _stages(self, db: AsyncSession, organization_id: uuid.UUID):
        return stage_repository(db, organization_id=organization_id)

    def _contacts(self, db: AsyncSession, organization_id: uuid.UUID):
        return contact_repository(db, organization_id=organization_id)

    def _accounts(self, db: AsyncSession, organization_id: uuid.UUID):
        return account_repository(db, organization_id=organization_id)

    @staticmethod
    def _assert_can_mutate(actor: CrmActor | None, deal: CrmDeal) -> None:
        if actor is None or actor.can_mutate_deal(deal):
            return
        raise DealServiceError(
            "You do not have access to modify this deal.",
            status_code=403,
        )

    async def _load_for_mutation(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        *,
        actor: CrmActor | None,
    ) -> CrmDeal:
        """Org-scoped load, then 403 if operator cannot mutate the deal."""
        deal = await self._deals_unscoped(db, organization_id).get_with_relations_unscoped(
            deal_id
        )
        if deal is None:
            raise DealServiceError("Deal not found.", status_code=404)
        self._assert_can_mutate(actor, deal)
        return deal

    async def _log_event(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        event_type: str,
        deal_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        payload: dict | None = None,
    ) -> None:
        from app.services.crm.timeline_service import timeline_service

        await timeline_service.log_event(
            db,
            organization_id,
            event_type=event_type,
            deal_id=deal_id,
            contact_id=contact_id,
            actor_id=actor_id,
            payload=payload,
        )

    async def _dispatch_automations(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        trigger_type: AutomationTriggerType,
        deal: CrmDeal,
        *,
        context_extra: dict | None = None,
    ) -> None:
        """
        Run automation rules for a deal mutation.

        Prefers Celery ``crm_actions`` queue; falls back to inline execution so
        unit tests / broker-down environments still apply actions in-session.
        """
        from app.config import settings
        from app.services.crm.automation_executor_service import (
            automation_executor_service,
            enqueue_automation_run,
        )

        use_celery = bool(getattr(settings, "CRM_AUTOMATIONS_USE_CELERY", False))
        if use_celery and enqueue_automation_run(
            organization_id=organization_id,
            deal_id=deal.id,
            trigger_type=trigger_type,
            context_extra=context_extra,
        ):
            return
        try:
            await automation_executor_service.run_triggers(
                db,
                trigger_type,
                deal,
                context_extra=context_extra,
            )
        except Exception as exc:
            logger.exception(
                "CRM.automation_dispatch_failed | deal_id={deal_id} trigger={trigger} error={error}",
                deal_id=deal.id,
                trigger=trigger_type.value,
                error=str(exc),
            )

    @staticmethod
    def _to_read(deal: CrmDeal) -> CrmDealRead:
        return CrmDealRead.model_validate(deal)

    async def _assert_stage_in_pipeline(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        pipeline_id: uuid.UUID,
        stage_id: uuid.UUID,
    ) -> None:
        stage = await self._stages(db, organization_id).get_in_pipeline(pipeline_id, stage_id)
        if stage is None:
            raise DealServiceError(
                "stage_id does not belong to the given pipeline_id (or is outside this organization).",
                status_code=400,
            )

    async def list_deals(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        actor: CrmActor | None = None,
        pipeline_id: uuid.UUID | None = None,
        stage_id: uuid.UUID | None = None,
        status: DealStatus | None = None,
        contact_id: uuid.UUID | None = None,
        account_id: uuid.UUID | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CrmDealListResponse:
        repo = self._deals(db, organization_id, actor=actor)
        items = await repo.get_deals(
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            status=status,
            contact_id=contact_id,
            account_id=account_id,
            q=q,
            limit=limit,
            offset=offset,
        )
        total = await repo.count_deals(
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            status=status,
            contact_id=contact_id,
            account_id=account_id,
            q=q,
        )
        return CrmDealListResponse(
            items=[self._to_read(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_deal(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        *,
        actor: CrmActor | None = None,
    ) -> CrmDealRead:
        deal = await self._deals(db, organization_id, actor=actor).get_with_relations(deal_id)
        if deal is None:
            raise DealServiceError("Deal not found.", status_code=404)
        return self._to_read(deal)

    async def create_deal(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmDealCreate,
        *,
        actor: CrmActor | None = None,
        actor_id: uuid.UUID | None = None,
        skip_automations: bool = False,
    ) -> CrmDealRead:
        pipelines = self._pipelines(db, organization_id)
        if await pipelines.get(payload.pipeline_id) is None:
            raise DealServiceError("Pipeline not found.", status_code=404)

        await self._assert_stage_in_pipeline(
            db,
            organization_id,
            pipeline_id=payload.pipeline_id,
            stage_id=payload.stage_id,
        )

        if payload.contact_id is not None:
            if await self._contacts(db, organization_id).get(payload.contact_id) is None:
                raise DealServiceError("Contact not found in this organization.", status_code=404)
        if payload.account_id is not None:
            if await self._accounts(db, organization_id).get(payload.account_id) is None:
                raise DealServiceError("Account not found in this organization.", status_code=404)

        resolved_actor_id = actor_id or (actor.user_id if actor else None)

        from app.services.quota_service import QuotaExceeded, quota_service

        try:
            await quota_service.assert_crm_deals_open_quota(db, organization_id)
        except QuotaExceeded as exc:
            raise DealServiceError(exc.detail, status_code=402) from exc

        deal = CrmDeal(
            organization_id=organization_id,
            pipeline_id=payload.pipeline_id,
            stage_id=payload.stage_id,
            contact_id=payload.contact_id,
            account_id=payload.account_id,
            bot_id=payload.bot_id,
            assigned_user_id=payload.assigned_user_id,
            title=payload.title,
            amount=payload.amount if payload.amount is not None else Decimal("0.00"),
            currency=payload.currency,
            status=DealStatus.OPEN,
            source=payload.source,
            custom_fields=dict(payload.custom_fields or {}),
        )
        await self._deals_unscoped(db, organization_id).add(deal)
        await self._log_event(
            db,
            organization_id,
            event_type="deal_created",
            deal_id=deal.id,
            contact_id=deal.contact_id,
            actor_id=resolved_actor_id,
            payload={
                "pipeline_id": str(deal.pipeline_id),
                "stage_id": str(deal.stage_id),
                "title": deal.title,
            },
        )
        try:
            from app.models.saas_metering import UsageMetricType
            from app.services.crm.crm_usage_events import record_crm_usage_event

            await record_crm_usage_event(
                db,
                organization_id=organization_id,
                metric_type=UsageMetricType.DEAL_CREATED,
                user_id=resolved_actor_id or deal.assigned_user_id,
                meta={"deal_id": str(deal.id), "pipeline_id": str(deal.pipeline_id)},
            )
        except Exception as exc:
            logger.warning(
                "CRM.usage_event_skipped | action=create deal_id={deal_id} error={error}",
                deal_id=deal.id,
                error=str(exc),
            )
        if not skip_automations:
            await self._dispatch_automations(
                db,
                organization_id,
                AutomationTriggerType.DEAL_CREATED,
                deal,
            )
        refreshed = await self._deals_unscoped(db, organization_id).get_with_relations_unscoped(
            deal.id
        )
        assert refreshed is not None
        result = self._to_read(refreshed)
        try:
            from app.services.crm.crm_ws import publish_deal_created

            publish_deal_created(organization_id, result, actor_id=resolved_actor_id)
        except Exception as exc:
            logger.warning(
                "CRM.ws_notify_skipped | action=create deal_id={deal_id} error={error}",
                deal_id=result.id,
                error=str(exc),
            )
        try:
            from app.services.crm.webhook_dispatcher_service import notify_partner_webhooks

            await notify_partner_webhooks(
                db,
                organization_id,
                "deal.created",
                result.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.warning(
                "CRM.webhook_notify_skipped | action=create deal_id={deal_id} error={error}",
                deal_id=result.id,
                error=str(exc),
            )
        return result

    async def update_deal(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        payload: CrmDealUpdate,
        *,
        actor: CrmActor | None = None,
    ) -> CrmDealRead:
        deal = await self._load_for_mutation(db, organization_id, deal_id, actor=actor)

        data = payload.model_dump(exclude_unset=True)
        if "contact_id" in data and data["contact_id"] is not None:
            if await self._contacts(db, organization_id).get(data["contact_id"]) is None:
                raise DealServiceError("Contact not found in this organization.", status_code=404)
        if "account_id" in data and data["account_id"] is not None:
            if await self._accounts(db, organization_id).get(data["account_id"]) is None:
                raise DealServiceError("Account not found in this organization.", status_code=404)

        for key, value in data.items():
            setattr(deal, key, value)
        await db.flush()
        refreshed = await self._deals_unscoped(db, organization_id).get_with_relations_unscoped(
            deal_id
        )
        assert refreshed is not None
        result = self._to_read(refreshed)
        if data:
            try:
                from app.services.crm.webhook_dispatcher_service import notify_partner_webhooks

                await notify_partner_webhooks(
                    db,
                    organization_id,
                    "deal.updated",
                    result.model_dump(mode="json"),
                )
            except Exception as exc:
                logger.warning(
                    "CRM.webhook_notify_skipped | action=update deal_id={deal_id} error={error}",
                    deal_id=result.id,
                    error=str(exc),
                )
        return result

    async def delete_deal(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        *,
        actor: CrmActor | None = None,
    ) -> None:
        # Delete is OWNER/ADMIN-only at the API layer; still enforce global scope here.
        if actor is not None and not actor.sees_all_deals:
            raise DealServiceError(
                "You do not have permission to delete deals.",
                status_code=403,
            )
        repo = self._deals_unscoped(db, organization_id)
        deal = await repo.get_unscoped(deal_id)
        if deal is None:
            raise DealServiceError("Deal not found.", status_code=404)
        await repo.delete(deal)

    async def move_stage(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        new_stage_id: uuid.UUID,
        *,
        actor: CrmActor | None = None,
        actor_id: uuid.UUID | None = None,
        skip_automations: bool = False,
    ) -> CrmDealRead:
        deal = await self._load_for_mutation(db, organization_id, deal_id, actor=actor)

        await self._assert_stage_in_pipeline(
            db,
            organization_id,
            pipeline_id=deal.pipeline_id,
            stage_id=new_stage_id,
        )

        previous_stage_id = deal.stage_id
        deal.stage_id = new_stage_id
        await db.flush()
        resolved_actor_id = actor_id or (actor.user_id if actor else None)
        await self._log_event(
            db,
            organization_id,
            event_type="stage_changed",
            deal_id=deal.id,
            contact_id=deal.contact_id,
            actor_id=resolved_actor_id,
            payload={
                "old_stage_id": str(previous_stage_id),
                "new_stage_id": str(new_stage_id),
            },
        )
        logger.info(
            "CRM.deal_moved | deal_id={deal_id} from={from_stage} to={to_stage}",
            deal_id=deal_id,
            from_stage=previous_stage_id,
            to_stage=new_stage_id,
        )
        if not skip_automations:
            await self._dispatch_automations(
                db,
                organization_id,
                AutomationTriggerType.STAGE_ENTERED,
                deal,
                context_extra={
                    "old_stage_id": str(previous_stage_id),
                    "new_stage_id": str(new_stage_id),
                },
            )
        refreshed = await self._deals_unscoped(db, organization_id).get_with_relations_unscoped(
            deal_id
        )
        assert refreshed is not None
        result = self._to_read(refreshed)
        try:
            from app.services.crm.crm_ws import publish_deal_updated

            publish_deal_updated(
                organization_id,
                deal_id=result.id,
                stage_id=result.stage_id,
                pipeline_id=result.pipeline_id,
                actor_id=resolved_actor_id,
            )
        except Exception as exc:
            logger.warning(
                "CRM.ws_notify_skipped | action=move deal_id={deal_id} error={error}",
                deal_id=result.id,
                error=str(exc),
            )
        try:
            from app.services.crm.webhook_dispatcher_service import notify_partner_webhooks

            await notify_partner_webhooks(
                db,
                organization_id,
                "deal.updated",
                {
                    **result.model_dump(mode="json"),
                    "old_stage_id": str(previous_stage_id),
                    "new_stage_id": str(new_stage_id),
                },
            )
        except Exception as exc:
            logger.warning(
                "CRM.webhook_notify_skipped | action=move deal_id={deal_id} error={error}",
                deal_id=result.id,
                error=str(exc),
            )
        return result

    async def close_deal(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        deal_id: uuid.UUID,
        payload: CrmDealCloseRequest,
        *,
        actor: CrmActor | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> CrmDealRead:
        deal = await self._load_for_mutation(db, organization_id, deal_id, actor=actor)

        deal.status = payload.status
        deal.closed_at = datetime.now(timezone.utc)
        await db.flush()
        resolved_actor_id = actor_id or (actor.user_id if actor else None)
        await self._log_event(
            db,
            organization_id,
            event_type="deal_closed",
            deal_id=deal.id,
            contact_id=deal.contact_id,
            actor_id=resolved_actor_id,
            payload={"status": payload.status.value},
        )
        try:
            from app.models.saas_metering import UsageMetricType
            from app.services.crm.crm_usage_events import record_crm_usage_event

            close_metric = (
                UsageMetricType.DEAL_WON
                if payload.status == DealStatus.WON
                else UsageMetricType.DEAL_LOST
            )
            await record_crm_usage_event(
                db,
                organization_id=organization_id,
                metric_type=close_metric,
                user_id=resolved_actor_id or deal.assigned_user_id,
                meta={
                    "deal_id": str(deal.id),
                    "status": payload.status.value,
                    "amount": str(deal.amount),
                },
            )
        except Exception as exc:
            logger.warning(
                "CRM.usage_event_skipped | action=close deal_id={deal_id} error={error}",
                deal_id=deal.id,
                error=str(exc),
            )
        logger.info(
            "CRM.deal_closed | deal_id={deal_id} status={status}",
            deal_id=deal_id,
            status=payload.status.value,
        )
        refreshed = await self._deals_unscoped(db, organization_id).get_with_relations_unscoped(
            deal_id
        )
        assert refreshed is not None
        result = self._to_read(refreshed)
        try:
            from app.services.crm.crm_ws import publish_deal_closed

            publish_deal_closed(
                organization_id,
                deal_id=result.id,
                status=result.status.value,
                actor_id=resolved_actor_id,
            )
        except Exception as exc:
            logger.warning(
                "CRM.ws_notify_skipped | action=close deal_id={deal_id} error={error}",
                deal_id=result.id,
                error=str(exc),
            )
        try:
            from app.services.crm.webhook_dispatcher_service import notify_partner_webhooks

            await notify_partner_webhooks(
                db,
                organization_id,
                "deal.closed",
                result.model_dump(mode="json"),
            )
        except Exception as exc:
            logger.warning(
                "CRM.webhook_notify_skipped | action=close deal_id={deal_id} error={error}",
                deal_id=result.id,
                error=str(exc),
            )
        return result


deal_service = DealService()
