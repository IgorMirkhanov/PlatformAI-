"""Native CRM Phase A step 3 — deals."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.deals import router as crm_deals_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.users import User
from app.schemas.crm.deals import (
    CrmDealCloseRequest,
    CrmDealCreate,
    CrmDealMoveStageRequest,
)
from app.services.crm.deal_service import DealService, DealServiceError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(*, org_id: uuid.UUID) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@crm.test",
        hashed_password="!",
        company_name="Org",
        full_name="CRM Tester",
        company_id=org_id,
        role=UserRole.OWNER,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


class CrmStore:
    def __init__(self) -> None:
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}


class FlushSession:
    async def flush(self) -> None:
        return None


class FakePipelineRepo:
    def __init__(self, store: CrmStore, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row


class FakeStageRepo:
    def __init__(self, store: CrmStore, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get_in_pipeline(
        self, pipeline_id: uuid.UUID, stage_id: uuid.UUID
    ) -> CrmStage | None:
        row = self.store.stages.get(stage_id)
        if (
            row is None
            or row.organization_id != self.organization_id
            or row.pipeline_id != pipeline_id
        ):
            return None
        return row


class FakeContactRepo:
    def __init__(self, store: CrmStore, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, contact_id: uuid.UUID) -> CrmContact | None:
        row = self.store.contacts.get(contact_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row


class FakeAccountRepo:
    def __init__(self, store: CrmStore, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, _account_id: uuid.UUID) -> Any:
        return None


class FakeDealRepo:
    def __init__(self, store: CrmStore, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    def _attach(self, deal: CrmDeal) -> CrmDeal:
        deal.stage = self.store.stages.get(deal.stage_id)
        deal.contact = (
            self.store.contacts.get(deal.contact_id) if deal.contact_id else None
        )
        deal.pipeline = self.store.pipelines.get(deal.pipeline_id)
        deal.account = None
        return deal

    async def add(self, entity: CrmDeal) -> CrmDeal:
        entity.organization_id = self.organization_id
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.deals[entity.id] = entity
        return entity

    async def get(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = self.store.deals.get(deal_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_with_relations(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = await self.get(deal_id)
        return self._attach(row) if row else None

    async def get_with_relations_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get_with_relations(deal_id)

    async def get_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get(deal_id)

    async def get_deals(self, **filters: Any) -> list[CrmDeal]:
        rows = [d for d in self.store.deals.values() if d.organization_id == self.organization_id]
        if filters.get("pipeline_id"):
            rows = [d for d in rows if d.pipeline_id == filters["pipeline_id"]]
        if filters.get("stage_id"):
            rows = [d for d in rows if d.stage_id == filters["stage_id"]]
        if filters.get("status"):
            rows = [d for d in rows if d.status == filters["status"]]
        if filters.get("contact_id"):
            rows = [d for d in rows if d.contact_id == filters["contact_id"]]
        limit = int(filters.get("limit") or 50)
        offset = int(filters.get("offset") or 0)
        rows = sorted(rows, key=lambda d: d.updated_at, reverse=True)
        return [self._attach(d) for d in rows[offset : offset + limit]]

    async def count_deals(self, **filters: Any) -> int:
        return len(await self.get_deals(**{**filters, "limit": 10_000, "offset": 0}))

    async def count_for_pipeline(self, pipeline_id: uuid.UUID) -> int:
        return sum(
            1
            for d in self.store.deals.values()
            if d.organization_id == self.organization_id and d.pipeline_id == pipeline_id
        )

    async def delete(self, entity: CrmDeal) -> None:
        self.store.deals.pop(entity.id, None)


def _seed_funnel(store: CrmStore, org_id: uuid.UUID) -> tuple[CrmPipeline, CrmStage, CrmStage, CrmContact]:
    pipeline = CrmPipeline(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Продажи",
        position=0,
        is_default=True,
        created_at=_now(),
        updated_at=_now(),
    )
    stage_a = CrmStage(
        id=uuid.uuid4(),
        organization_id=org_id,
        pipeline_id=pipeline.id,
        name="Новый лид",
        position=0,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    stage_b = CrmStage(
        id=uuid.uuid4(),
        organization_id=org_id,
        pipeline_id=pipeline.id,
        name="Переговоры",
        position=1,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    contact = CrmContact(
        id=uuid.uuid4(),
        organization_id=org_id,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        created_at=_now(),
        updated_at=_now(),
        custom_fields={},
    )
    store.pipelines[pipeline.id] = pipeline
    store.stages[stage_a.id] = stage_a
    store.stages[stage_b.id] = stage_b
    store.contacts[contact.id] = contact
    return pipeline, stage_a, stage_b, contact


def _bind_deal_service(store: CrmStore) -> DealService:
    service = DealService()
    service._deals = lambda _db, org_id, **_kw: FakeDealRepo(store, org_id)  # type: ignore[method-assign]
    service._pipelines = lambda _db, org_id: FakePipelineRepo(store, org_id)  # type: ignore[method-assign]
    service._stages = lambda _db, org_id: FakeStageRepo(store, org_id)  # type: ignore[method-assign]
    service._contacts = lambda _db, org_id: FakeContactRepo(store, org_id)  # type: ignore[method-assign]
    service._accounts = lambda _db, org_id: FakeAccountRepo(store, org_id)  # type: ignore[method-assign]

    async def _noop_log(*_args: Any, **_kwargs: Any) -> None:
        return None

    service._log_event = _noop_log  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_create_and_list_deal_with_contact() -> None:
    store = CrmStore()
    service = _bind_deal_service(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed_funnel(store, org)

    created = await service.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="WhatsApp lead",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
            amount=Decimal("15000.00"),
        ),
    )
    assert created.organization_id == org
    assert created.contact is not None
    assert created.contact.first_name == "Ada"
    assert created.stage is not None
    assert created.stage.name == "Новый лид"

    listed = await service.list_deals(db, org, pipeline_id=pipeline.id)  # type: ignore[arg-type]
    assert listed.total == 1
    assert listed.items[0].id == created.id
    assert listed.items[0].contact is not None


@pytest.mark.asyncio
async def test_create_rejects_stage_from_other_pipeline() -> None:
    store = CrmStore()
    service = _bind_deal_service(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, _, _, _ = _seed_funnel(store, org)

    foreign_stage = CrmStage(
        id=uuid.uuid4(),
        organization_id=org,
        pipeline_id=uuid.uuid4(),  # different pipeline
        name="Foreign",
        position=0,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    store.stages[foreign_stage.id] = foreign_stage

    with pytest.raises(DealServiceError) as exc:
        await service.create_deal(
            db,  # type: ignore[arg-type]
            org,
            CrmDealCreate(
                title="Bad",
                pipeline_id=pipeline.id,
                stage_id=foreign_stage.id,
            ),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_move_stage_rejects_foreign_stage() -> None:
    store = CrmStore()
    service = _bind_deal_service(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed_funnel(store, org)
    deal = await service.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Move me",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
    )
    foreign = CrmStage(
        id=uuid.uuid4(),
        organization_id=org,
        pipeline_id=uuid.uuid4(),
        name="Other funnel stage",
        position=0,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    store.stages[foreign.id] = foreign

    with pytest.raises(DealServiceError) as exc:
        await service.move_stage(db, org, deal.id, foreign.id)  # type: ignore[arg-type]
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_move_stage_and_close_deal() -> None:
    store = CrmStore()
    service = _bind_deal_service(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, stage_a, stage_b, contact = _seed_funnel(store, org)
    deal = await service.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Close me",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
    )

    moved = await service.move_stage(db, org, deal.id, stage_b.id)  # type: ignore[arg-type]
    assert moved.stage_id == stage_b.id

    closed = await service.close_deal(
        db,  # type: ignore[arg-type]
        org,
        deal.id,
        CrmDealCloseRequest(status=DealStatus.WON),
    )
    assert closed.status == DealStatus.WON
    assert closed.closed_at is not None


@pytest.mark.asyncio
async def test_tenant_isolation_deals() -> None:
    store = CrmStore()
    service = _bind_deal_service(store)
    db = FlushSession()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed_funnel(store, org_a)
    deal = await service.create_deal(
        db,  # type: ignore[arg-type]
        org_a,
        CrmDealCreate(
            title="Private",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
    )

    listed_b = await service.list_deals(db, org_b)  # type: ignore[arg-type]
    assert listed_b.total == 0
    with pytest.raises(DealServiceError) as exc:
        await service.get_deal(db, org_b, deal.id)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_cross_tenant_deal_404(monkeypatch: pytest.MonkeyPatch) -> None:
    store = CrmStore()
    service = _bind_deal_service(store)
    db = FlushSession()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed_funnel(store, org_a)
    deal = await service.create_deal(
        db,  # type: ignore[arg-type]
        org_a,
        CrmDealCreate(
            title="Secret deal",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
    )
    monkeypatch.setattr("app.api.endpoints.crm.deals.deal_service", service)

    app = FastAPI()
    app.include_router(crm_deals_router, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: _make_user(org_id=org_b)
    # Nested role gate still resolves via get_current_user; also override the CRM gate.
    from app.api.endpoints.crm.deps import require_crm_deal_access

    app.dependency_overrides[require_crm_deal_access] = lambda: _make_user(org_id=org_b)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/crm/deals/{deal.id}")
        listed = await client.get("/api/v1/crm/deals")
        move = await client.post(
            f"/api/v1/crm/deals/{deal.id}/move-stage",
            json={"stage_id": str(stage_a.id)},
        )

    assert response.status_code == 404
    assert listed.status_code == 200
    assert listed.json()["total"] == 0
    assert move.status_code == 404


def test_migration_031_crm_deals() -> None:
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "031_crm_deals.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "crm_deals" in text
    assert "030_crm_accounts_contacts" in text
    assert "Numeric(12, 2)" in text
    assert "ck_crm_deals_status" in text


def test_no_direct_crm_deal_selects_outside_repos() -> None:
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    pattern = re.compile(r"select\(\s*CrmDeal\b")
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
