"""Native CRM — pipeline / stage business logic."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.repositories.crm.pipeline_repository import PipelineRepository, pipeline_repository
from app.repositories.crm.stage_repository import StageRepository, stage_repository
from app.schemas.crm.pipelines import (
    CrmPipelineCreate,
    CrmPipelineRead,
    CrmPipelineUpdate,
    CrmStageCreate,
    CrmStageRead,
    CrmStageUpdate,
)

DEFAULT_PIPELINE_NAME = "Продажи"
DEFAULT_STAGES: tuple[dict[str, Any], ...] = (
    {"name": "Новый лид", "position": 0, "color": "#94A3B8", "is_won": False, "is_lost": False},
    {"name": "Квалификация", "position": 1, "color": "#38BDF8", "is_won": False, "is_lost": False},
    {"name": "Предложение", "position": 2, "color": "#A78BFA", "is_won": False, "is_lost": False},
    {"name": "Переговоры", "position": 3, "color": "#FBBF24", "is_won": False, "is_lost": False},
    {"name": "Выиграна", "position": 4, "color": "#34D399", "is_won": True, "is_lost": False},
    {"name": "Проиграна", "position": 5, "color": "#F87171", "is_won": False, "is_lost": True},
)


class PipelineServiceError(Exception):
    """Domain error for CRM pipeline operations."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class PipelineService:
    """Pipelines + stages for a single tenant organization."""

    def _repos(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> tuple[PipelineRepository, StageRepository]:
        return (
            pipeline_repository(db, organization_id=organization_id),
            stage_repository(db, organization_id=organization_id),
        )

    @staticmethod
    def _to_read(pipeline: CrmPipeline) -> CrmPipelineRead:
        stages = sorted(pipeline.stages or [], key=lambda s: (s.position, str(s.id)))
        return CrmPipelineRead(
            id=pipeline.id,
            organization_id=pipeline.organization_id,
            name=pipeline.name,
            position=pipeline.position,
            is_default=pipeline.is_default,
            stages=[CrmStageRead.model_validate(stage) for stage in stages],
            created_at=pipeline.created_at,
            updated_at=pipeline.updated_at,
        )

    async def create_default_pipeline(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> CrmPipelineRead:
        """
        Seed the default «Продажи» funnel for a new organization.

        Idempotent: if a default pipeline already exists, return it.
        """
        pipelines, stages = self._repos(db, organization_id)
        existing = await pipelines.get_default()
        if existing is not None:
            return self._to_read(existing)

        try:
            async with db.begin_nested():
                pipeline = CrmPipeline(
                    organization_id=organization_id,
                    name=DEFAULT_PIPELINE_NAME,
                    position=0,
                    is_default=True,
                )
                await pipelines.add(pipeline)
                for spec in DEFAULT_STAGES:
                    await stages.add(
                        CrmStage(
                            organization_id=organization_id,
                            pipeline_id=pipeline.id,
                            name=str(spec["name"]),
                            position=int(spec["position"]),
                            color=spec.get("color"),
                            is_won=bool(spec["is_won"]),
                            is_lost=bool(spec["is_lost"]),
                        )
                    )
                await db.flush()
        except IntegrityError:
            existing = await pipelines.get_default()
            if existing is not None:
                return self._to_read(existing)
            raise
        refreshed = await pipelines.get_with_stages(pipeline.id)
        assert refreshed is not None
        logger.info(
            "CRM.default_pipeline_seeded | organization_id={organization_id} pipeline_id={pipeline_id}",
            organization_id=organization_id,
            pipeline_id=pipeline.id,
        )
        return self._to_read(refreshed)

    async def list_pipelines(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[CrmPipelineRead]:
        pipelines, _ = self._repos(db, organization_id)
        rows = await pipelines.list_with_stages()
        return [self._to_read(row) for row in rows]

    async def create_pipeline(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmPipelineCreate,
    ) -> CrmPipelineRead:
        pipelines, _ = self._repos(db, organization_id)
        position = (
            payload.position
            if payload.position is not None
            else await pipelines.next_position()
        )
        if payload.is_default:
            await self._clear_default_flag(db, organization_id)

        pipeline = CrmPipeline(
            organization_id=organization_id,
            name=payload.name,
            position=position,
            is_default=payload.is_default,
        )
        await pipelines.add(pipeline)
        refreshed = await pipelines.get_with_stages(pipeline.id)
        assert refreshed is not None
        return self._to_read(refreshed)

    async def update_pipeline(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        payload: CrmPipelineUpdate,
    ) -> CrmPipelineRead:
        pipelines, _ = self._repos(db, organization_id)
        pipeline = await pipelines.get_with_stages(pipeline_id)
        if pipeline is None:
            raise PipelineServiceError("Pipeline not found.", status_code=404)

        data = payload.model_dump(exclude_unset=True)
        if data.get("is_default") is True:
            await self._clear_default_flag(db, organization_id, except_id=pipeline_id)
        for key, value in data.items():
            setattr(pipeline, key, value)
        await db.flush()
        refreshed = await pipelines.get_with_stages(pipeline_id)
        assert refreshed is not None
        return self._to_read(refreshed)

    async def delete_pipeline(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        pipeline_id: uuid.UUID,
    ) -> None:
        pipelines, _ = self._repos(db, organization_id)
        pipeline = await pipelines.get(pipeline_id)
        if pipeline is None:
            raise PipelineServiceError("Pipeline not found.", status_code=404)

        # Refuse delete when deals still reference this pipeline (FK RESTRICT).
        from app.repositories.crm.deal_repository import deal_repository

        deal_count = await deal_repository(db, organization_id=organization_id).count_for_pipeline(
            pipeline_id
        )
        if deal_count > 0:
            raise PipelineServiceError(
                f"Cannot delete pipeline while {deal_count} deal(s) still reference it.",
                status_code=409,
            )

        await pipelines.delete(pipeline)

    async def create_stage(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        payload: CrmStageCreate,
    ) -> CrmStageRead:
        pipelines, stages = self._repos(db, organization_id)
        pipeline = await pipelines.get(pipeline_id)
        if pipeline is None:
            raise PipelineServiceError("Pipeline not found.", status_code=404)

        position = (
            payload.position
            if payload.position is not None
            else await stages.next_position(pipeline_id)
        )
        stage = CrmStage(
            organization_id=organization_id,
            pipeline_id=pipeline_id,
            name=payload.name,
            position=position,
            color=payload.color,
            is_won=payload.is_won,
            is_lost=payload.is_lost,
        )
        try:
            await stages.add(stage)
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise PipelineServiceError(
                "Pipeline already has a won or lost stage of this type.",
                status_code=409,
            ) from exc
        return CrmStageRead.model_validate(stage)

    async def update_stage(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        stage_id: uuid.UUID,
        payload: CrmStageUpdate,
    ) -> CrmStageRead:
        _, stages = self._repos(db, organization_id)
        stage = await stages.get_in_pipeline(pipeline_id, stage_id)
        if stage is None:
            raise PipelineServiceError("Stage not found.", status_code=404)

        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(stage, key, value)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise PipelineServiceError(
                "Pipeline already has a won or lost stage of this type.",
                status_code=409,
            ) from exc
        return CrmStageRead.model_validate(stage)

    async def delete_stage(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        stage_id: uuid.UUID,
    ) -> None:
        _, stages = self._repos(db, organization_id)
        stage = await stages.get_in_pipeline(pipeline_id, stage_id)
        if stage is None:
            raise PipelineServiceError("Stage not found.", status_code=404)
        await stages.delete(stage)

    async def reorder_stages(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        positions: list[tuple[uuid.UUID, int]],
    ) -> list[CrmStageRead]:
        pipelines, stages = self._repos(db, organization_id)
        pipeline = await pipelines.get(pipeline_id)
        if pipeline is None:
            raise PipelineServiceError("Pipeline not found.", status_code=404)

        updated = await stages.reorder_in_pipeline(pipeline_id, positions)
        if updated == 0 and positions:
            raise PipelineServiceError(
                "No matching stages found for reorder.",
                status_code=400,
            )
        rows = await stages.list_for_pipeline(pipeline_id)
        return [CrmStageRead.model_validate(row) for row in rows]

    async def _clear_default_flag(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        except_id: uuid.UUID | None = None,
    ) -> None:
        pipelines, _ = self._repos(db, organization_id)
        for row in await pipelines.list_with_stages():
            if except_id is not None and row.id == except_id:
                continue
            if row.is_default:
                row.is_default = False
        await db.flush()


pipeline_service = PipelineService()
