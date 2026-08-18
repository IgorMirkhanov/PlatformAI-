"""Native CRM Phase A step 4 — activities, notes, timeline."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.timeline import router as crm_timeline_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.crm.activity import ActivityType, CrmActivity
from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.note import CrmNote
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.crm.timeline_event import CrmTimelineEvent
from app.models.users import User
from app.schemas.crm.activities_notes import CrmActivityCreate, CrmNoteCreate
from app.schemas.crm.deals import CrmDealCreate
from app.services.crm.activity_service import ActivityService, ActivityServiceError
from app.services.crm.deal_service import DealService
from app.services.crm.note_service import NoteService
from app.services.crm.timeline_service import TimelineService


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


class Store:
    def __init__(self) -> None:
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}
        self.activities: dict[uuid.UUID, CrmActivity] = {}
        self.notes: dict[uuid.UUID, CrmNote] = {}
        self.events: dict[uuid.UUID, CrmTimelineEvent] = {}


class FlushSession:
    async def flush(self) -> None:
        return None


class FakeDealRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    def _attach(self, deal: CrmDeal) -> CrmDeal:
        deal.stage = self.store.stages.get(deal.stage_id)
        deal.contact = self.store.contacts.get(deal.contact_id) if deal.contact_id else None
        deal.pipeline = self.store.pipelines.get(deal.pipeline_id)
        deal.account = None
        return deal

    async def add(self, entity: CrmDeal) -> CrmDeal:
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


class FakePipelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row


class FakeStageRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get_in_pipeline(self, pipeline_id: uuid.UUID, stage_id: uuid.UUID) -> CrmStage | None:
        row = self.store.stages.get(stage_id)
        if (
            row is None
            or row.organization_id != self.organization_id
            or row.pipeline_id != pipeline_id
        ):
            return None
        return row


class FakeContactRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, contact_id: uuid.UUID) -> CrmContact | None:
        row = self.store.contacts.get(contact_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row


class FakeAccountRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, _account_id: uuid.UUID) -> Any:
        return None


class FakeActivityRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmActivity) -> CrmActivity:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        self.store.activities[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmActivity | None:
        row = self.store.activities.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def list_filtered(self, **filters: Any) -> list[CrmActivity]:
        rows = [a for a in self.store.activities.values() if a.organization_id == self.organization_id]
        if filters.get("deal_id"):
            rows = [a for a in rows if a.deal_id == filters["deal_id"]]
        limit = int(filters.get("limit") or 50)
        offset = int(filters.get("offset") or 0)
        return rows[offset : offset + limit]

    async def count_filtered(self, **filters: Any) -> int:
        return len(await self.list_filtered(**{**filters, "limit": 10_000, "offset": 0}))

    async def delete(self, entity: CrmActivity) -> None:
        self.store.activities.pop(entity.id, None)


class FakeNoteRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmNote) -> CrmNote:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        self.store.notes[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmNote | None:
        row = self.store.notes.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def list_filtered(self, **filters: Any) -> list[CrmNote]:
        rows = [n for n in self.store.notes.values() if n.organization_id == self.organization_id]
        if filters.get("deal_id"):
            rows = [n for n in rows if n.deal_id == filters["deal_id"]]
        limit = int(filters.get("limit") or 50)
        offset = int(filters.get("offset") or 0)
        return rows[offset : offset + limit]

    async def count_filtered(self, **filters: Any) -> int:
        return len(await self.list_filtered(**{**filters, "limit": 10_000, "offset": 0}))

    async def delete(self, entity: CrmNote) -> None:
        self.store.notes.pop(entity.id, None)


class FakeTimelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmTimelineEvent) -> CrmTimelineEvent:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.payload = dict(getattr(entity, "payload", None) or {})
        self.store.events[entity.id] = entity
        return entity

    async def list_events(self, **filters: Any) -> list[CrmTimelineEvent]:
        rows = [e for e in self.store.events.values() if e.organization_id == self.organization_id]
        if filters.get("deal_id"):
            rows = [e for e in rows if e.deal_id == filters["deal_id"]]
        if filters.get("contact_id"):
            rows = [e for e in rows if e.contact_id == filters["contact_id"]]
        rows = sorted(rows, key=lambda e: e.created_at, reverse=True)
        limit = int(filters.get("limit") or 100)
        offset = int(filters.get("offset") or 0)
        return rows[offset : offset + limit]

    async def count_events(self, **filters: Any) -> int:
        return len(await self.list_events(**{**filters, "limit": 10_000, "offset": 0}))


def _seed(store: Store, org_id: uuid.UUID) -> tuple[CrmPipeline, CrmStage, CrmStage, CrmContact]:
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
        created_at=_now(),
        updated_at=_now(),
        custom_fields={},
    )
    store.pipelines[pipeline.id] = pipeline
    store.stages[stage_a.id] = stage_a
    store.stages[stage_b.id] = stage_b
    store.contacts[contact.id] = contact
    return pipeline, stage_a, stage_b, contact


def _bind_all(store: Store) -> tuple[DealService, ActivityService, NoteService, TimelineService]:
    import sys

    import app.services.crm.note_service as note_mod

    # Package __init__ shadows the submodule name with the singleton instance.
    timeline_mod = sys.modules["app.services.crm.timeline_service"]
    tls: TimelineService = timeline_mod.timeline_service

    fake_timeline_repo = lambda _db, org: FakeTimelineRepo(store, org)

    deals = DealService()
    deals._deals = lambda _db, org, **_kw: FakeDealRepo(store, org)  # type: ignore[method-assign]
    deals._pipelines = lambda _db, org: FakePipelineRepo(store, org)  # type: ignore[method-assign]
    deals._stages = lambda _db, org: FakeStageRepo(store, org)  # type: ignore[method-assign]
    deals._contacts = lambda _db, org: FakeContactRepo(store, org)  # type: ignore[method-assign]
    deals._accounts = lambda _db, org: FakeAccountRepo(store, org)  # type: ignore[method-assign]

    # note_service / deal_service use the module singleton — patch its repo factory
    tls._repo = fake_timeline_repo  # type: ignore[method-assign]
    note_mod.timeline_service = tls

    async def _log(
        db: Any,
        organization_id: uuid.UUID,
        *,
        event_type: str,
        deal_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        payload: dict | None = None,
    ) -> None:
        await tls.log_event(
            db,
            organization_id,
            event_type=event_type,
            deal_id=deal_id,
            contact_id=contact_id,
            actor_id=actor_id,
            payload=payload,
        )

    deals._log_event = _log  # type: ignore[method-assign]

    activities = ActivityService()
    activities._repo = lambda _db, org: FakeActivityRepo(store, org)  # type: ignore[method-assign]

    async def _assert_activity_targets(
        db: Any,
        organization_id: uuid.UUID,
        *,
        deal_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
    ) -> None:
        if deal_id is not None and await FakeDealRepo(store, organization_id).get(deal_id) is None:
            raise ActivityServiceError("Deal not found.", status_code=404)
        if contact_id is not None and await FakeContactRepo(store, organization_id).get(contact_id) is None:
            raise ActivityServiceError("Contact not found.", status_code=404)

    activities._assert_targets = _assert_activity_targets  # type: ignore[method-assign]

    notes = NoteService()
    notes._repo = lambda _db, org: FakeNoteRepo(store, org)  # type: ignore[method-assign]

    async def _assert_note_targets(
        db: Any,
        organization_id: uuid.UUID,
        *,
        deal_id: uuid.UUID | None,
        contact_id: uuid.UUID | None,
    ) -> None:
        if deal_id is not None and await FakeDealRepo(store, organization_id).get(deal_id) is None:
            from app.services.crm.note_service import NoteServiceError

            raise NoteServiceError("Deal not found.", status_code=404)
        if contact_id is not None and await FakeContactRepo(store, organization_id).get(contact_id) is None:
            from app.services.crm.note_service import NoteServiceError

            raise NoteServiceError("Contact not found.", status_code=404)

    notes._assert_targets = _assert_note_targets  # type: ignore[method-assign]

    return deals, activities, notes, tls


@pytest.mark.asyncio
async def test_activity_crud_and_complete() -> None:
    store = Store()
    deals, activities, _, _ = _bind_all(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed(store, org)
    deal = await deals.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Act deal",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
            amount=Decimal("1"),
        ),
        actor_id=uuid.uuid4(),
    )
    created = await activities.create_activity(
        db,  # type: ignore[arg-type]
        org,
        CrmActivityCreate(title="Call back", type=ActivityType.CALL, deal_id=deal.id),
        created_by_id=uuid.uuid4(),
    )
    assert created.deal_id == deal.id
    completed = await activities.complete_activity(db, org, created.id)  # type: ignore[arg-type]
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_note_crud_logs_timeline() -> None:
    store = Store()
    deals, activities, notes, timeline = _bind_all(store)
    db = FlushSession()
    org = uuid.uuid4()
    actor = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed(store, org)
    deal = await deals.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Note deal",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
        actor_id=actor,
    )
    note = await notes.create_note(
        db,  # type: ignore[arg-type]
        org,
        CrmNoteCreate(text="Follow up tomorrow", deal_id=deal.id),
        author_id=actor,
    )
    events = await timeline.get_events(db, org, deal_id=deal.id)  # type: ignore[arg-type]
    types = {e.event_type for e in events.items}
    assert "note_added" in types
    assert note.id is not None


@pytest.mark.asyncio
async def test_deal_mutations_write_timeline_and_api_lists_them() -> None:
    store = Store()
    deals, _, _, timeline = _bind_all(store)
    db = FlushSession()
    org = uuid.uuid4()
    actor = uuid.uuid4()
    pipeline, stage_a, stage_b, contact = _seed(store, org)

    deal = await deals.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Timeline deal",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
        actor_id=actor,
    )
    await deals.move_stage(db, org, deal.id, stage_b.id, actor_id=actor)  # type: ignore[arg-type]

    events = await timeline.get_events(db, org, deal_id=deal.id)  # type: ignore[arg-type]
    by_type = {e.event_type: e for e in events.items}
    assert "deal_created" in by_type
    assert "stage_changed" in by_type
    assert by_type["deal_created"].actor_id == actor
    assert by_type["stage_changed"].actor_id == actor
    assert by_type["stage_changed"].payload["old_stage_id"] == str(stage_a.id)
    assert by_type["stage_changed"].payload["new_stage_id"] == str(stage_b.id)

    # HTTP list timeline
    user = _make_user(org_id=org)
    user.id = actor

    import app.api.endpoints.crm.timeline as timeline_api

    timeline_api.timeline_service = timeline

    app = FastAPI()
    app.include_router(crm_timeline_router, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/crm/timeline?deal_id={deal.id}")

    assert response.status_code == 200
    body = response.json()
    types = {item["event_type"] for item in body["items"]}
    assert "deal_created" in types
    assert "stage_changed" in types
    for item in body["items"]:
        if item["event_type"] in {"deal_created", "stage_changed"}:
            assert item["actor_id"] == str(actor)


def test_migration_032_exists() -> None:
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "032_crm_activities_notes_timeline.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "crm_activities" in text
    assert "crm_notes" in text
    assert "crm_timeline_events" in text
    assert "031_crm_deals" in text
    assert 'ondelete="CASCADE"' in text


def test_no_direct_selects_outside_repos() -> None:
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    pattern = re.compile(r"select\(\s*Crm(Activity|Note|TimelineEvent)\b")
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
