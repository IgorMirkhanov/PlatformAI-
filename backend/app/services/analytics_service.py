"""Product analytics façade over UsageEvent (Stripe metering friendly)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saas_metering import UsageEvent, UsageMetricType


class AnalyticsService:
    """
    Aggregates usage for dashboards and Stripe metered billing stubs.

    Does not call external SaaS (PostHog/Segment) — keeps events in Postgres
    so tenants stay data-sovereign for v1.0.
    """

    async def org_summary(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        days: int = 30,
    ) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=max(1, days))
        rows = await db.execute(
            select(
                UsageEvent.metric_type,
                func.coalesce(func.sum(UsageEvent.quantity), 0),
                func.coalesce(func.sum(UsageEvent.total_cost), 0),
            )
            .where(
                UsageEvent.organization_id == organization_id,
                UsageEvent.created_at >= since,
            )
            .group_by(UsageEvent.metric_type)
        )
        metrics: dict[str, Any] = {}
        for metric, qty, cost in rows.all():
            key = metric.value if isinstance(metric, UsageMetricType) else str(metric)
            metrics[key] = {"quantity": int(qty or 0), "cost": float(cost or 0)}

        logger.debug(
            "Analytics.org_summary | org={org} days={days} keys={keys}",
            org=organization_id,
            days=days,
            keys=list(metrics.keys()),
        )
        return {
            "organization_id": str(organization_id),
            "period_days": days,
            "since": since.isoformat(),
            "metrics": metrics,
            "message_count": int(
                (metrics.get("MESSAGE_IN", {}) or {}).get("quantity", 0)
                + (metrics.get("MESSAGE_OUT", {}) or {}).get("quantity", 0)
            ),
            "estimated_cost": sum(v.get("cost", 0) for v in metrics.values()),
        }

    def stripe_meter_payload(
        self,
        *,
        stripe_customer_id: str,
        metric: UsageMetricType,
        quantity: int,
    ) -> dict[str, Any]:
        """Stub payload for Stripe billing meters (Phase 1 wiring)."""
        return {
            "customer": stripe_customer_id,
            "event_name": metric.value.lower(),
            "payload": {"value": max(0, int(quantity))},
            "timestamp": int(datetime.now(UTC).timestamp()),
        }


analytics_service = AnalyticsService()
