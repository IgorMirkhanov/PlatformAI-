"""Hub metering: dual-write integration_usage_events + billing usage_events.

Billing bridge target table is ``usage_events`` (SaaS metering / wallet analytics).
Idempotency keys (action_id / event_id / celery task id) prevent double-charge on
Celery retries of the same CRM/messaging action.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import UserRole
from app.models.integration_hub import IntegrationConnection, IntegrationUsageEvent
from app.models.saas_metering import UsageEvent, UsageMetricType
from app.models.users import User
from app.services.usage_service import usage_service

_METRIC_TO_BILLING: dict[str, UsageMetricType] = {
    "wazzup_webhook": UsageMetricType.MESSAGE_IN,
    "wazzup_outbound": UsageMetricType.MESSAGE_OUT,
    "bitrix24_webhook": UsageMetricType.CRM_CALL,
    "bitrix24_rest": UsageMetricType.CRM_CALL,
    "amocrm_webhook": UsageMetricType.CRM_CALL,
    "amocrm_rest": UsageMetricType.CRM_CALL,
    "kaspi_pay_webhook": UsageMetricType.CRM_CALL,
    "kaspi_pay_invoice": UsageMetricType.CRM_CALL,
    "hub_adapter_ok": UsageMetricType.CRM_CALL,
}


def build_hub_action_idempotency_key(
    *,
    connection_id: uuid.UUID | str,
    action_type: str,
    action_id: str | None = None,
    event_id: str | None = None,
    task_id: str | None = None,
) -> str | None:
    """Stable key for one CRM/messaging action across Celery retries."""
    token = (action_id or event_id or task_id or "").strip()
    if not token:
        return None
    action = (action_type or "action").strip().lower()[:64]
    return f"hub:{connection_id}:{action}:{token}"[:255]


async def _billing_actor_id(db: AsyncSession, organization_id: uuid.UUID) -> uuid.UUID | None:
    """Prefer workspace OWNER, else any member — UsageEvent.user_id is required."""
    owner = await db.scalar(
        select(User.id)
        .where(User.company_id == organization_id, User.role == UserRole.OWNER)
        .limit(1)
    )
    if owner is not None:
        return owner
    return await db.scalar(select(User.id).where(User.company_id == organization_id).limit(1))


async def _existing_by_idempotency(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    idempotency_key: str,
) -> IntegrationUsageEvent | None:
    return await db.scalar(
        select(IntegrationUsageEvent).where(
            IntegrationUsageEvent.organization_id == organization_id,
            IntegrationUsageEvent.idempotency_key == idempotency_key,
        )
    )


async def record_hub_usage(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    metric: str,
    quantity: int = 1,
    bridge_billing: bool = True,
    meta: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> IntegrationUsageEvent | None:
    """Atomically write integration + billing meters (same DB transaction).

    Returns the integration row when a *new* meter was written; ``None`` when
    the idempotency key already existed (retry — no second billing write).
    """
    qty = max(1, int(quantity))
    meta_payload = dict(meta or {})
    key = (idempotency_key or meta_payload.get("idempotency_key") or "").strip() or None
    if key:
        meta_payload["idempotency_key"] = key

    if key:
        existing = await _existing_by_idempotency(
            db, organization_id=connection.organization_id, idempotency_key=key
        )
        if existing is not None:
            logger.info(
                "HubUsage.idempotent_skip | org={org} key={key} metric={metric}",
                org=connection.organization_id,
                key=key,
                metric=metric,
            )
            return None

        row_id = uuid.uuid4()
        stmt = (
            pg_insert(IntegrationUsageEvent)
            .values(
                id=row_id,
                connection_id=connection.id,
                organization_id=connection.organization_id,
                metric=metric[:64],
                quantity=qty,
                idempotency_key=key,
            )
            .on_conflict_do_nothing(
                index_elements=["organization_id", "idempotency_key"],
                index_where=text("idempotency_key IS NOT NULL"),
            )
            .returning(IntegrationUsageEvent.id)
        )
        inserted_id = await db.scalar(stmt)
        if inserted_id is None:
            logger.info(
                "HubUsage.idempotent_conflict | org={org} key={key}",
                org=connection.organization_id,
                key=key,
            )
            return None
        row = await db.get(IntegrationUsageEvent, inserted_id)
    else:
        row = IntegrationUsageEvent(
            connection_id=connection.id,
            organization_id=connection.organization_id,
            metric=metric[:64],
            quantity=qty,
            idempotency_key=None,
        )
        db.add(row)
        await db.flush()

    if not bridge_billing or row is None:
        return row

    billing_metric = _METRIC_TO_BILLING.get(metric)
    if billing_metric is None:
        return row

    actor_id = await _billing_actor_id(db, connection.organization_id)
    if actor_id is None:
        logger.debug(
            "HubUsage.billing_skipped | org={org} metric={metric} reason=no_user",
            org=connection.organization_id,
            metric=metric,
        )
        return row

    if key:
        # Belt-and-suspenders: skip if billing meter already has this idempotency key.
        prior = await db.scalar(
            select(UsageEvent.id)
            .where(
                UsageEvent.organization_id == connection.organization_id,
                UsageEvent.meta.contains({"idempotency_key": key}),
            )
            .limit(1)
        )
        if prior is not None:
            logger.info(
                "HubUsage.billing_idempotent_skip | org={org} key={key}",
                org=connection.organization_id,
                key=key,
            )
            return row

    try:
        await usage_service.record_and_debit(
            db,
            user_id=actor_id,
            organization_id=connection.organization_id,
            bot_id=connection.bot_id,
            metric_type=billing_metric,
            quantity=qty,
            unit_cost=0,
            debit_wallet=False,
            meta={
                "source": "integration_hub",
                "billing_usage_events": True,
                "hub_metric": metric,
                "connection_id": str(connection.id),
                "provider": connection.provider,
                **meta_payload,
            },
        )
    except Exception as exc:
        logger.warning(
            "HubUsage.billing_bridge_failed | org={org} metric={metric} error={error}",
            org=connection.organization_id,
            metric=metric,
            error=str(exc),
        )
        # Re-raise so the outer transaction rolls back both writes when possible.
        raise
    return row
