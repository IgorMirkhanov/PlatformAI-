"""Record non-billable CRM usage meters for platform analytics / Org ROI."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saas_metering import UsageMetricType
from app.services.usage_service import usage_service


async def record_crm_usage_event(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    metric_type: UsageMetricType,
    user_id: uuid.UUID | None,
    meta: dict[str, Any] | None = None,
) -> None:
    """
    Append a UsageEvent without wallet debit.

    ``UsageEvent.user_id`` is required by the metering schema — when no actor
    is available the event is skipped (still logged for observability).
    """
    if user_id is None:
        logger.debug(
            "CRM.usage_event_skipped | org={org} metric={metric} reason=no_user",
            org=organization_id,
            metric=metric_type.value,
        )
        return
    try:
        await usage_service.record_and_debit(
            db,
            user_id=user_id,
            organization_id=organization_id,
            metric_type=metric_type,
            quantity=1,
            unit_cost=0,
            debit_wallet=False,
            meta=meta or {},
        )
    except Exception as exc:
        logger.warning(
            "CRM.usage_event_failed | org={org} metric={metric} error={error}",
            org=organization_id,
            metric=metric_type.value,
            error=str(exc),
        )
