"""Native CRM Phase B step 3 — per-deal RBAC scoping for operators."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.deals import router as crm_deals_router
from app.api.endpoints.crm.deps import require_crm_deal_access, require_crm_deal_admin
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.users import User
from app.schemas.crm.deals import CrmDealCreate, CrmDealUpdate
from app.services.crm.deal_access import CrmActor
from app.services.crm.deal_service import DealService, DealServiceError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(*, org_id: uuid.UUID, role: UserRole, user_id: uuid.UUID | None = None) -> User:
    uid = user_id or uuid.uuid4()
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


class CrmStore:
    def __init__(self) -> None:
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}


class FlushSession:
    async def flush(self) -> None:
        return None


class FakeDealRepo:
    """Mirrors DealRepository viewer scoping for unit tests."""

    def __init__(
        self,
        store: CrmStore,
        organization_id: uuid.UUID,
        *,
        actor: CrmActor | None = None,
    ) -> None:
        self.store = store
        self.organization_id = organization_id
        self.actor = actor

    def _visible(self, deal: CrmDeal) -> bool:
        if deal.organization_id != self.organization_id:
            return False
        if self.actor is None or self.actor.sees_all_deals:
            return True
        return self.actor.can_view_deal(deal)

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
        if row is None or not self._visible(row):
            return None
        return row

    async def get_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = self.store.deals.get(deal_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_with_relations(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = await self.get(deal_id)
        return self._attach(row) if row else None

    async def get_with_relations_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = await self.get_unscoped(deal_id)
        return self._attach(row) if row else None

    async def get_deals(self, **filters: Any) -> list[CrmDeal]:
        rows = [d for d in self.store.deals.values() if self._visible(d)]
        if filters.get("pipeline_id"):
            rows = [d for d in rows if d.pipeline_id == filters["pipeline_id"]]
        limit = int(filters.get("limit") or 50)
        offset = int(filters.get("offset") or 0)
        rows = sorted(rows, key=lambda d: d.updated_at, reverse=True)
        return [self._attach(d) for d in rows[offset : offset + limit]]

    async def count_deals(self, **filters: Any) -> int:
        return len(await self.get_deals(**{**filters, "limit": 10_000, "offset": 0}))

    async def delete(self, entity: CrmDeal) -> None:
        self.store.deals.pop(entity.id, None)


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


def _seed(store: CrmStore, org: uuid.UUID) -> tuple[CrmPipeline, CrmStage, CrmContact]:
    pipeline = CrmPipeline(
        id=uuid.uuid4(),
        organization_id=org,
        name="Sales",
        position=0,
        is_default=True,
        created_at=_now(),
        updated_at=_now(),
    )
    stage = CrmStage(
        id=uuid.uuid4(),
        organization_id=org,
        pipeline_id=pipeline.id,
        name="New",
        position=0,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    contact = CrmContact(
        id=uuid.uuid4(),
        organization_id=org,
        first_name="Ada",
        last_name="Lovelace",
        created_at=_now(),
        updated_at=_now(),
        custom_fields={},
    )
    store.pipelines[pipeline.id] = pipeline
    store.stages[stage.id] = stage
    store.contacts[contact.id] = contact
    return pipeline, stage, contact


def _bind(store: CrmStore) -> DealService:
    service = DealService()

    def _deals(_db: Any, org_id: uuid.UUID, *, actor: CrmActor | None = None):
        return FakeDealRepo(store, org_id, actor=actor)

    service._deals = _deals  # type: ignore[method-assign]
    service._pipelines = lambda _db, org_id: FakePipelineRepo(store, org_id)  # type: ignore[method-assign]
    service._stages = lambda _db, org_id: FakeStageRepo(store, org_id)  # type: ignore[method-assign]
    service._contacts = lambda _db, org_id: FakeContactRepo(store, org_id)  # type: ignore[method-assign]
    service._accounts = lambda _db, org_id: FakeAccountRepo(store, org_id)  # type: ignore[method-assign]

    async def _noop_log(*_a: Any, **_k: Any) -> None:
        return None

    async def _noop_auto(*_a: Any, **_k: Any) -> None:
        return None

    service._log_event = _noop_log  # type: ignore[method-assign]
    service._dispatch_automations = _noop_auto  # type: ignore[method-assign]
    return service


async def _seed_three_deals(
    service: DealService,
    store: CrmStore,
    db: FlushSession,
    org: uuid.UUID,
    *,
    op_a: uuid.UUID,
    op_b: uuid.UUID,
) -> tuple[CrmDeal, CrmDeal, CrmDeal]:
    pipeline, stage, contact = _seed(store, org)
    unassigned = await service.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Unassigned",
            pipeline_id=pipeline.id,
            stage_id=stage.id,
            contact_id=contact.id,
        ),
    )
    mine = await service.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Mine",
            pipeline_id=pipeline.id,
            stage_id=stage.id,
            contact_id=contact.id,
            assigned_user_id=op_a,
        ),
    )
    theirs = await service.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Theirs",
            pipeline_id=pipeline.id,
            stage_id=stage.id,
            contact_id=contact.id,
            assigned_user_id=op_b,
        ),
    )
    return store.deals[unassigned.id], store.deals[mine.id], store.deals[theirs.id]


@pytest.mark.asyncio
async def test_admin_lists_all_deals() -> None:
    store = CrmStore()
    service = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    op_a = uuid.uuid4()
    op_b = uuid.uuid4()
    await _seed_three_deals(service, store, db, org, op_a=op_a, op_b=op_b)

    admin = CrmActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)
    listed = await service.list_deals(db, org, actor=admin)  # type: ignore[arg-type]
    assert listed.total == 3
    assert {d.title for d in listed.items} == {"Unassigned", "Mine", "Theirs"}

    owner = CrmActor(user_id=uuid.uuid4(), role=UserRole.OWNER)
    listed_owner = await service.list_deals(db, org, actor=owner)  # type: ignore[arg-type]
    assert listed_owner.total == 3


@pytest.mark.asyncio
async def test_operator_sees_only_own_and_unassigned() -> None:
    store = CrmStore()
    service = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    op_a = uuid.uuid4()
    op_b = uuid.uuid4()
    unassigned, mine, theirs = await _seed_three_deals(
        service, store, db, org, op_a=op_a, op_b=op_b
    )

    actor_a = CrmActor(user_id=op_a, role=UserRole.OPERATOR)
    listed = await service.list_deals(db, org, actor=actor_a)  # type: ignore[arg-type]
    assert listed.total == 2
    assert {d.title for d in listed.items} == {"Unassigned", "Mine"}

    got_mine = await service.get_deal(db, org, mine.id, actor=actor_a)  # type: ignore[arg-type]
    assert got_mine.id == mine.id

    got_open = await service.get_deal(db, org, unassigned.id, actor=actor_a)  # type: ignore[arg-type]
    assert got_open.id == unassigned.id

    with pytest.raises(DealServiceError) as exc:
        await service.get_deal(db, org, theirs.id, actor=actor_a)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_operator_cannot_mutate_foreign_deal() -> None:
    store = CrmStore()
    service = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    op_a = uuid.uuid4()
    op_b = uuid.uuid4()
    _, _, theirs = await _seed_three_deals(service, store, db, org, op_a=op_a, op_b=op_b)

    actor_a = CrmActor(user_id=op_a, role=UserRole.OPERATOR)
    with pytest.raises(DealServiceError) as exc_upd:
        await service.update_deal(
            db,  # type: ignore[arg-type]
            org,
            theirs.id,
            CrmDealUpdate(title="Hijack"),
            actor=actor_a,
        )
    assert exc_upd.value.status_code == 403

    pipeline = next(iter(store.pipelines.values()))
    stage = next(iter(store.stages.values()))
    with pytest.raises(DealServiceError) as exc_move:
        await service.move_stage(
            db,  # type: ignore[arg-type]
            org,
            theirs.id,
            stage.id,
            actor=actor_a,
        )
    assert exc_move.value.status_code == 403
    assert store.deals[theirs.id].title == "Theirs"


@pytest.mark.asyncio
async def test_operator_can_mutate_unassigned_and_own() -> None:
    store = CrmStore()
    service = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    op_a = uuid.uuid4()
    op_b = uuid.uuid4()
    unassigned, mine, _ = await _seed_three_deals(
        service, store, db, org, op_a=op_a, op_b=op_b
    )
    actor_a = CrmActor(user_id=op_a, role=UserRole.OPERATOR)

    updated = await service.update_deal(
        db,  # type: ignore[arg-type]
        org,
        unassigned.id,
        CrmDealUpdate(title="Claimed pool", assigned_user_id=op_a),
        actor=actor_a,
    )
    assert updated.title == "Claimed pool"
    assert updated.assigned_user_id == op_a

    updated_mine = await service.update_deal(
        db,  # type: ignore[arg-type]
        org,
        mine.id,
        CrmDealUpdate(title="Still mine"),
        actor=actor_a,
    )
    assert updated_mine.title == "Still mine"


@pytest.mark.asyncio
async def test_api_operator_forbidden_on_foreign_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CrmStore()
    service = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    op_a = uuid.uuid4()
    op_b = uuid.uuid4()
    _, _, theirs = await _seed_three_deals(service, store, db, org, op_a=op_a, op_b=op_b)

    monkeypatch.setattr("app.api.endpoints.crm.deals.deal_service", service)

    app = FastAPI()
    app.include_router(crm_deals_router, prefix="/api/v1")

    async def _override_db():
        yield db

    operator = _make_user(org_id=org, role=UserRole.OPERATOR, user_id=op_a)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: operator
    app.dependency_overrides[require_crm_deal_access] = lambda: operator
    app.dependency_overrides[require_crm_deal_admin] = lambda: operator

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/v1/crm/deals")
        get_foreign = await client.get(f"/api/v1/crm/deals/{theirs.id}")
        patch_foreign = await client.patch(
            f"/api/v1/crm/deals/{theirs.id}",
            json={"title": "Nope"},
        )
        move_foreign = await client.post(
            f"/api/v1/crm/deals/{theirs.id}/move-stage",
            json={"stage_id": str(next(iter(store.stages)))},
        )

    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert get_foreign.status_code == 404
    assert patch_foreign.status_code == 403
    assert move_foreign.status_code == 403


def test_crm_actor_helpers() -> None:
    op = CrmActor(user_id=uuid.uuid4(), role=UserRole.OPERATOR)
    admin = CrmActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)
    assert op.sees_all_deals is False
    assert admin.sees_all_deals is True

    deal = CrmDeal(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        pipeline_id=uuid.uuid4(),
        stage_id=uuid.uuid4(),
        title="x",
        amount=Decimal("0"),
        currency="KZT",
        status=DealStatus.OPEN,
        assigned_user_id=admin.user_id,
        custom_fields={},
    )
    assert op.can_view_deal(deal) is False
    assert admin.can_view_deal(deal) is True
