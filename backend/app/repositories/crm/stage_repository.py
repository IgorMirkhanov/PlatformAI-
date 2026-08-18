"""CRM stage repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.stage import CrmStage
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class StageRepository(BaseCrmRepository[CrmStage]):
    model = CrmStage

    async def list_for_pipeline(self, pipeline_id: uuid.UUID) -> list[CrmStage]:
        stmt = (
            self._base_query()
            .where(CrmStage.pipeline_id == pipeline_id)
            .order_by(CrmStage.position.asc(), CrmStage.created_at.asc())
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def get_in_pipeline(
        self,
        pipeline_id: uuid.UUID,
        stage_id: uuid.UUID,
    ) -> CrmStage | None:
        stmt = self._base_query().where(
            CrmStage.pipeline_id == pipeline_id,
            CrmStage.id == stage_id,
        )
        return await self.session.scalar(stmt)

    async def next_position(self, pipeline_id: uuid.UUID) -> int:
        stmt = select(CrmStage.position).where(
            CrmStage.organization_id == self.organization_id,
            CrmStage.pipeline_id == pipeline_id,
        )
        result = await self.session.scalars(stmt)
        positions = list(result.all())
        return (max(positions) + 1) if positions else 0

    async def reorder_in_pipeline(
        self,
        pipeline_id: uuid.UUID,
        positions: list[tuple[uuid.UUID, int]],
    ) -> int:
        """Reorder stages that belong to ``pipeline_id`` within this tenant."""
        if not positions:
            return 0
        # Validate membership first so foreign pipeline ids cannot be touched.
        existing = {stage.id: stage for stage in await self.list_for_pipeline(pipeline_id)}
        updated = 0
        for stage_id, position in positions:
            stage = existing.get(stage_id)
            if stage is None:
                continue
            stage.position = int(position)
            updated += 1
        await self.session.flush()
        return updated


def stage_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> StageRepository:
    return StageRepository(session, organization_id=organization_id)
