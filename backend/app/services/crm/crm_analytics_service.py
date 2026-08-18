"""Native CRM analytics — SQL aggregates over deals (tenant-scoped)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.crm.analytics_repository import analytics_repository
from app.schemas.crm.analytics import (
    CrmForecastResponse,
    CrmFunnelResponse,
    CrmPerformanceResponse,
    FunnelStageStat,
    ManagerPerformanceRow,
)


class CrmAnalyticsServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _as_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class CrmAnalyticsService:
    """
    Organization-scoped CRM reports.

    Aggregations run in PostgreSQL via repository SQL (``func.count`` /
    ``func.sum`` / ``group_by``) — never by loading full deal lists.
    """

    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return analytics_repository(db, organization_id=organization_id)

    async def get_pipeline_funnel(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> CrmFunnelResponse:
        repo = self._repo(db, organization_id)
        if not await repo.pipeline_belongs(pipeline_id):
            raise CrmAnalyticsServiceError("Pipeline not found.", status_code=404)

        stage_rows = await repo.funnel_stage_rows(
            pipeline_id, start_date=start_date, end_date=end_date
        )
        totals_row = await repo.funnel_totals(
            pipeline_id, start_date=start_date, end_date=end_date
        )
        total_i = int(totals_row.total_deals or 0)
        won_i = int(totals_row.won_deals or 0)
        conversion = (won_i / total_i) if total_i > 0 else 0.0

        stages = [
            FunnelStageStat(
                stage_id=row.stage_id,
                stage_name=row.stage_name,
                position=int(row.position),
                deal_count=int(row.deal_count or 0),
                amount_sum=_as_decimal(row.amount_sum),
            )
            for row in stage_rows
        ]

        logger.debug(
            "CRM.analytics_funnel | org={org} pipeline={pipeline} stages={n} "
            "total={total} won={won} conversion={conv:.4f}",
            org=organization_id,
            pipeline=pipeline_id,
            n=len(stages),
            total=total_i,
            won=won_i,
            conv=conversion,
        )
        return CrmFunnelResponse(
            pipeline_id=pipeline_id,
            stages=stages,
            total_deals=total_i,
            won_deals=won_i,
            conversion_rate=conversion,
        )

    async def get_manager_performance(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> CrmPerformanceResponse:
        rows = await self._repo(db, organization_id).manager_performance_rows(
            start_date=start_date,
            end_date=end_date,
        )
        items = [
            ManagerPerformanceRow(
                assigned_user_id=row.assigned_user_id,
                won_count=int(row.won_count or 0),
                lost_count=int(row.lost_count or 0),
                revenue=_as_decimal(row.revenue),
            )
            for row in rows
        ]
        logger.debug(
            "CRM.analytics_performance | org={org} managers={n}",
            org=organization_id,
            n=len(items),
        )
        return CrmPerformanceResponse(items=items)

    async def get_revenue_forecast(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> CrmForecastResponse:
        forecast_row = await self._repo(db, organization_id).revenue_forecast_row()
        result = CrmForecastResponse(
            open_deal_count=int(forecast_row.open_deal_count or 0),
            forecast_amount=_as_decimal(forecast_row.forecast_amount),
        )
        logger.debug(
            "CRM.analytics_forecast | org={org} open={open} amount={amount}",
            org=organization_id,
            open=result.open_deal_count,
            amount=str(result.forecast_amount),
        )
        return result


crm_analytics_service = CrmAnalyticsService()
