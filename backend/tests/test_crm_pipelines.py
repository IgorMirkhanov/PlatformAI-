"""Native CRM Phase A step 1 — pipelines / stages."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.api.endpoints.crm.pipelines import router as crm_pipelines_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.users import User
from app.schemas.crm.pipelines import CrmPipelineUpdate, CrmStageCreate
from app.services.crm.pipeline_service import (
    DEFAULT_STAGES,
    PipelineService,
    PipelineServiceError,
    pipeline_service,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(*, org_id: uuid.UUID, role: UserRole = UserRole.OWNER) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@crm.test",
        hashed_password="!",
        company_name="Org",
        full_name="CRM Tester",
        company_id=org_id,
        role=role,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


class FakeStageRepo:
    def __init__(self, store: "CrmStore", organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmStage) -> CrmStage:
        entity.organization_id = self.organization_id
        entity.id = entity.id or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        self.store.assert_won_lost_unique(entity)
        self.store.stages[entity.id] = entity
        pipeline = self.store.pipelines.get(entity.pipeline_id)
        if pipeline is not None:
            pipeline.stages = [s for s in (pipeline.stages or []) if s.id != entity.id] + [entity]
        return entity

    async def list_for_pipeline(self, pipeline_id: uuid.UUID) -> list[CrmStage]:
        rows = [
            s
            for s in self.store.stages.values()
            if s.organization_id == self.organization_id and s.pipeline_id == pipeline_id
        ]
        return sorted(rows, key=lambda s: (s.position, str(s.id)))

    async def get_in_pipeline(self, pipeline_id: uuid.UUID, stage_id: uuid.UUID) -> CrmStage | None:
        stage = self.store.stages.get(stage_id)
        if (
            stage is None
            or stage.organization_id != self.organization_id
            or stage.pipeline_id != pipeline_id
        ):
            return None
        return stage

    async def next_position(self, pipeline_id: uuid.UUID) -> int:
        rows = await self.list_for_pipeline(pipeline_id)
        return (max(s.position for s in rows) + 1) if rows else 0

    async def reorder_in_pipeline(
        self,
        pipeline_id: uuid.UUID,
        positions: list[tuple[uuid.UUID, int]],
    ) -> int:
        existing = {s.id: s for s in await self.list_for_pipeline(pipeline_id)}
        updated = 0
        for stage_id, position in positions:
            stage = existing.get(stage_id)
            if stage is None:
                continue
            stage.position = int(position)
            updated += 1
        return updated

    async def delete(self, entity: CrmStage) -> None:
        self.store.stages.pop(entity.id, None)
        pipeline = self.store.pipelines.get(entity.pipeline_id)
        if pipeline is not None:
            pipeline.stages = [s for s in (pipeline.stages or []) if s.id != entity.id]


class FakePipelineRepo:
    def __init__(self, store: "CrmStore", organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmPipeline) -> CrmPipeline:
        entity.organization_id = self.organization_id
        entity.id = entity.id or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.stages = list(getattr(entity, "stages", None) or [])
        self.store.pipelines[entity.id] = entity
        return entity

    async def list_with_stages(self, *, limit: int = 100) -> list[CrmPipeline]:
        rows = [
            p for p in self.store.pipelines.values() if p.organization_id == self.organization_id
        ][:limit]
        for pipeline in rows:
            pipeline.stages = await FakeStageRepo(self.store, self.organization_id).list_for_pipeline(
                pipeline.id
            )
        return sorted(rows, key=lambda p: (p.position, str(p.id)))

    async def get_with_stages(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        pipeline = self.store.pipelines.get(pipeline_id)
        if pipeline is None or pipeline.organization_id != self.organization_id:
            return None
        pipeline.stages = await FakeStageRepo(self.store, self.organization_id).list_for_pipeline(
            pipeline.id
        )
        return pipeline

    async def get(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        return await self.get_with_stages(pipeline_id)

    async def get_default(self) -> CrmPipeline | None:
        for pipeline in await self.list_with_stages():
            if pipeline.is_default:
                return pipeline
        return None

    async def next_position(self) -> int:
        rows = await self.list_with_stages()
        return (max(p.position for p in rows) + 1) if rows else 0

    async def delete(self, entity: CrmPipeline) -> None:
        self.store.pipelines.pop(entity.id, None)
        gone = [sid for sid, s in self.store.stages.items() if s.pipeline_id == entity.id]
        for sid in gone:
            self.store.stages.pop(sid, None)


class CrmStore:
    def __init__(self) -> None:
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}

    def assert_won_lost_unique(self, stage: CrmStage) -> None:
        for other in self.stages.values():
            if other.id == stage.id or other.pipeline_id != stage.pipeline_id:
                continue
            if stage.is_won and other.is_won:
                raise IntegrityError("uq_crm_stages_pipeline_won", {}, Exception())
            if stage.is_lost and other.is_lost:
                raise IntegrityError("uq_crm_stages_pipeline_lost", {}, Exception())


class FlushSession:
    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    def begin_nested(self):
        return _NestedSavepoint()


class _NestedSavepoint:
    async def __aenter__(self) -> "_NestedSavepoint":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


def _bind_service(store: CrmStore) -> PipelineService:
    service = PipelineService()

    def _repos(_db: Any, organization_id: uuid.UUID) -> tuple[FakePipelineRepo, FakeStageRepo]:
        return FakePipelineRepo(store, organization_id), FakeStageRepo(store, organization_id)

    service._repos = _repos  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_create_default_pipeline_seeds_stages() -> None:
    store = CrmStore()
    service = _bind_service(store)
    org_id = uuid.uuid4()
    db = FlushSession()

    result = await service.create_default_pipeline(db, org_id)  # type: ignore[arg-type]
    assert result.name == "Продажи"
    assert result.is_default is True
    assert len(result.stages) == len(DEFAULT_STAGES)
    assert [s.name for s in result.stages] == [s["name"] for s in DEFAULT_STAGES]
    assert sum(1 for s in result.stages if s.is_won) == 1
    assert sum(1 for s in result.stages if s.is_lost) == 1

    again = await service.create_default_pipeline(db, org_id)  # type: ignore[arg-type]
    assert again.id == result.id
    assert len(store.pipelines) == 1


@pytest.mark.asyncio
async def test_cross_tenant_pipeline_isolation() -> None:
    store = CrmStore()
    service = _bind_service(store)
    db = FlushSession()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    pipe_a = await service.create_default_pipeline(db, org_a)  # type: ignore[arg-type]
    pipe_b = await service.create_default_pipeline(db, org_b)  # type: ignore[arg-type]
    assert pipe_a.id != pipe_b.id

    listed_a = await service.list_pipelines(db, org_a)  # type: ignore[arg-type]
    listed_b = await service.list_pipelines(db, org_b)  # type: ignore[arg-type]
    assert {p.id for p in listed_a} == {pipe_a.id}
    assert {p.id for p in listed_b} == {pipe_b.id}

    with pytest.raises(PipelineServiceError) as exc:
        await service.update_pipeline(
            db,  # type: ignore[arg-type]
            org_b,
            pipe_a.id,
            CrmPipelineUpdate(name="Hacked"),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reorder_stages_applies_positions() -> None:
    store = CrmStore()
    service = _bind_service(store)
    db = FlushSession()
    org_id = uuid.uuid4()
    pipeline = await service.create_default_pipeline(db, org_id)  # type: ignore[arg-type]
    stage_ids = [s.id for s in pipeline.stages]
    positions = [(sid, idx) for idx, sid in enumerate(reversed(stage_ids))]
    reordered = await service.reorder_stages(db, org_id, pipeline.id, positions)  # type: ignore[arg-type]
    assert [s.id for s in reordered] == list(reversed(stage_ids))
    assert [s.position for s in reordered] == list(range(len(stage_ids)))


@pytest.mark.asyncio
async def test_partial_unique_won_stage_enforced() -> None:
    store = CrmStore()
    service = _bind_service(store)
    db = FlushSession()
    org_id = uuid.uuid4()
    pipeline = await service.create_default_pipeline(db, org_id)  # type: ignore[arg-type]

    with pytest.raises(PipelineServiceError) as exc:
        await service.create_stage(
            db,  # type: ignore[arg-type]
            org_id,
            pipeline.id,
            CrmStageCreate(name="Second Win", is_won=True),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_api_cross_tenant_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    store = CrmStore()
    service = _bind_service(store)
    db = FlushSession()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    pipe_a = await service.create_default_pipeline(db, org_a)  # type: ignore[arg-type]
    user_b = _make_user(org_id=org_b, role=UserRole.OWNER)

    monkeypatch.setattr(
        "app.api.endpoints.crm.pipelines.pipeline_service",
        service,
    )

    app = FastAPI()
    app.include_router(crm_pipelines_router, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user_b

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/crm/pipelines/{pipe_a.id}",
            json={"name": "Nope"},
        )
        listed = await client.get("/api/v1/crm/pipelines")

    assert response.status_code == 404
    assert listed.status_code == 200
    assert listed.json() == []


def test_migration_defines_partial_unique_indexes() -> None:
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "029_crm_pipelines_stages.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "uq_crm_stages_pipeline_won" in text
    assert "uq_crm_stages_pipeline_lost" in text
    assert "WHERE is_won IS TRUE" in text
    assert "WHERE is_lost IS TRUE" in text
    assert "028_db_indexes_opt" in text
    assert "029_crm_pipelines_stages" in text


def test_no_direct_crm_selects_outside_repositories() -> None:
    """Definition of Done: CRM selects live only in repositories/crm."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"select\(\s*Crm(Pipeline|Stage)\b")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if "repositories" in path.parts and "crm" in path.parts:
            continue
        if "models" in path.parts and "crm" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []
