"""CRM pipeline repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.crm.pipeline import CrmPipeline
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class PipelineRepository(BaseCrmRepository[CrmPipeline]):
    model = CrmPipeline

    async def list_with_stages(self, *, limit: int = 100) -> list[CrmPipeline]:
        stmt = (
            self._base_query()
            .options(selectinload(CrmPipeline.stages))
            .order_by(CrmPipeline.position.asc(), CrmPipeline.created_at.asc())
            .limit(limit)
        )
        result = await self.session.scalars(stmt)
        return list(result.unique().all())

    async def get_with_stages(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        stmt = (
            self._base_query()
            .where(CrmPipeline.id == pipeline_id)
            .options(selectinload(CrmPipeline.stages))
        )
        return await self.session.scalar(stmt)

    async def get_default(self) -> CrmPipeline | None:
        stmt = (
            self._base_query()
            .where(CrmPipeline.is_default.is_(True))
            .options(selectinload(CrmPipeline.stages))
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def next_position(self) -> int:
        stmt = select(CrmPipeline.position).where(
            CrmPipeline.organization_id == self.organization_id
        )
        result = await self.session.scalars(stmt)
        positions = list(result.all())
        return (max(positions) + 1) if positions else 0


def pipeline_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> PipelineRepository:
    return PipelineRepository(session, organization_id=organization_id)
