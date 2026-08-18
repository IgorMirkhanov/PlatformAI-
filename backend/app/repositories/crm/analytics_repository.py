"""CRM analytics repository — tenant-scoped SQL aggregates over deals/stages."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class CrmAnalyticsRepository(BaseCrmRepository[CrmDeal]):
    model = CrmDeal

    @staticmethod
    def _created_at_filters(
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list:
        filters: list = []
        if start_date is not None:
            filters.append(CrmDeal.created_at >= start_date)
        if end_date is not None:
            filters.append(CrmDeal.created_at <= end_date)
        return filters

    @staticmethod
    def _closed_at_filters(
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list:
        filters: list = []
        if start_date is not None:
            filters.append(CrmDeal.closed_at >= start_date)
        if end_date is not None:
            filters.append(CrmDeal.closed_at <= end_date)
        return filters

    async def pipeline_belongs(self, pipeline_id: uuid.UUID) -> bool:
        stmt = select(CrmPipeline.id).where(
            CrmPipeline.id == pipeline_id,
            CrmPipeline.organization_id == self.organization_id,
        )
        return await self.session.scalar(stmt) is not None

    async def funnel_stage_rows(
        self,
        pipeline_id: uuid.UUID,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Sequence[Any]:
        date_filters = self._created_at_filters(start_date, end_date)
        deal_match = and_(
            CrmDeal.stage_id == CrmStage.id,
            CrmDeal.organization_id == self.organization_id,
            CrmDeal.pipeline_id == pipeline_id,
            *date_filters,
        )
        stmt = (
            select(
                CrmStage.id.label("stage_id"),
                CrmStage.name.label("stage_name"),
                CrmStage.position.label("position"),
                func.count(CrmDeal.id).label("deal_count"),
                func.coalesce(func.sum(CrmDeal.amount), 0).label("amount_sum"),
            )
            .select_from(CrmStage)
            .outerjoin(CrmDeal, deal_match)
            .where(
                CrmStage.organization_id == self.organization_id,
                CrmStage.pipeline_id == pipeline_id,
            )
            .group_by(CrmStage.id, CrmStage.name, CrmStage.position)
            .order_by(CrmStage.position.asc())
        )
        return (await self.session.execute(stmt)).all()

    async def funnel_totals(
        self,
        pipeline_id: uuid.UUID,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Any:
        date_filters = self._created_at_filters(start_date, end_date)
        stmt = select(
            func.count(CrmDeal.id).label("total_deals"),
            func.coalesce(
                func.sum(case((CrmDeal.status == DealStatus.WON, 1), else_=0)),
                0,
            ).label("won_deals"),
        ).where(
            CrmDeal.organization_id == self.organization_id,
            CrmDeal.pipeline_id == pipeline_id,
            *date_filters,
        )
        return (await self.session.execute(stmt)).one()

    async def manager_performance_rows(
        self,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> Sequence[Any]:
        date_filters = self._closed_at_filters(start_date, end_date)
        stmt = (
            select(
                CrmDeal.assigned_user_id.label("assigned_user_id"),
                func.coalesce(
                    func.sum(case((CrmDeal.status == DealStatus.WON, 1), else_=0)),
                    0,
                ).label("won_count"),
                func.coalesce(
                    func.sum(case((CrmDeal.status == DealStatus.LOST, 1), else_=0)),
                    0,
                ).label("lost_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (CrmDeal.status == DealStatus.WON, CrmDeal.amount),
                            else_=0,
                        )
                    ),
                    0,
                ).label("revenue"),
            )
            .where(
                CrmDeal.organization_id == self.organization_id,
                CrmDeal.status.in_((DealStatus.WON, DealStatus.LOST)),
                *date_filters,
            )
            .group_by(CrmDeal.assigned_user_id)
            .order_by(
                func.coalesce(
                    func.sum(
                        case(
                            (CrmDeal.status == DealStatus.WON, CrmDeal.amount),
                            else_=0,
                        )
                    ),
                    0,
                ).desc()
            )
        )
        return (await self.session.execute(stmt)).all()

    async def revenue_forecast_row(self) -> Any:
        stmt = select(
            func.count(CrmDeal.id).label("open_deal_count"),
            func.coalesce(func.sum(CrmDeal.amount), 0).label("forecast_amount"),
        ).where(
            CrmDeal.organization_id == self.organization_id,
            CrmDeal.status == DealStatus.OPEN,
        )
        return (await self.session.execute(stmt)).one()


def analytics_repository(
    session: AsyncSession, *, organization_id: uuid.UUID
) -> CrmAnalyticsRepository:
    return CrmAnalyticsRepository(session, organization_id=organization_id)
