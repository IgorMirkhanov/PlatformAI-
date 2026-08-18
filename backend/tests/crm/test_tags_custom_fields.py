"""Native CRM Phase A step 5 — tags and custom field definitions."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from app.models.crm.custom_field import CrmCustomFieldDefinition, CrmEntityType, CrmFieldType
from app.models.crm.deal import CrmDeal
from app.models.crm.tag import CrmTag
from app.models.crm.timeline_event import CrmTimelineEvent
from app.schemas.crm.tags_fields import CrmCustomFieldCreate, CrmTagCreate, CrmTagUpdate
from app.services.crm.custom_field_service import CustomFieldService, CustomFieldServiceError
from app.services.crm.tag_service import TagService, TagServiceError
from app.services.crm.timeline_service import TimelineService


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self) -> None:
        self.tags: dict[uuid.UUID, CrmTag] = {}
        self.fields: dict[uuid.UUID, CrmCustomFieldDefinition] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}
        self.deal_tags: set[tuple[uuid.UUID, uuid.UUID]] = set()
        self.events: dict[uuid.UUID, CrmTimelineEvent] = {}


class FlushSession:
    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeTagRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmTag) -> CrmTag:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        self.store.tags[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmTag | None:
        row = self.store.tags.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def list_ordered(self, *, limit: int = 200, offset: int = 0) -> list[CrmTag]:
        rows = sorted(
            [t for t in self.store.tags.values() if t.organization_id == self.organization_id],
            key=lambda t: t.name,
        )
        return rows[offset : offset + limit]

    async def count_all(self) -> int:
        return len([t for t in self.store.tags.values() if t.organization_id == self.organization_id])

    async def delete(self, entity: CrmTag) -> None:
        self.store.tags.pop(entity.id, None)
        self.store.deal_tags = {(d, t) for d, t in self.store.deal_tags if t != entity.id}

    async def attach_to_deal(self, *, deal_id: uuid.UUID, tag_id: uuid.UUID) -> bool:
        key = (deal_id, tag_id)
        if key in self.store.deal_tags:
            return False
        self.store.deal_tags.add(key)
        return True

    async def detach_from_deal(self, *, deal_id: uuid.UUID, tag_id: uuid.UUID) -> bool:
        key = (deal_id, tag_id)
        if key not in self.store.deal_tags:
            return False
        self.store.deal_tags.remove(key)
        return True


class FakeDealRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = self.store.deals.get(deal_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row


class FakeFieldRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmCustomFieldDefinition) -> CrmCustomFieldDefinition:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        self.store.fields[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmCustomFieldDefinition | None:
        row = self.store.fields.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_by_key(
        self,
        *,
        entity_type: CrmEntityType,
        field_key: str,
    ) -> CrmCustomFieldDefinition | None:
        for row in self.store.fields.values():
            if (
                row.organization_id == self.organization_id
                and row.entity_type == entity_type
                and row.field_key == field_key
            ):
                return row
        return None

    async def list_filtered(
        self,
        *,
        entity_type: CrmEntityType | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[CrmCustomFieldDefinition]:
        rows = [f for f in self.store.fields.values() if f.organization_id == self.organization_id]
        if entity_type is not None:
            rows = [f for f in rows if f.entity_type == entity_type]
        rows = sorted(rows, key=lambda f: (f.entity_type.value, f.position, f.created_at))
        return rows[offset : offset + limit]

    async def count_filtered(self, *, entity_type: CrmEntityType | None = None) -> int:
        return len(await self.list_filtered(entity_type=entity_type, limit=10_000, offset=0))

    async def delete(self, entity: CrmCustomFieldDefinition) -> None:
        self.store.fields.pop(entity.id, None)


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
        rows = sorted(rows, key=lambda e: e.created_at, reverse=True)
        limit = int(filters.get("limit") or 100)
        offset = int(filters.get("offset") or 0)
        return rows[offset : offset + limit]

    async def count_events(self, **filters: Any) -> int:
        return len(await self.list_events(**{**filters, "limit": 10_000, "offset": 0}))


def _bind(store: Store) -> tuple[TagService, CustomFieldService, TimelineService]:
    tag_mod = sys.modules["app.services.crm.tag_service"]
    timeline_mod = sys.modules["app.services.crm.timeline_service"]

    tls: TimelineService = timeline_mod.timeline_service
    tls._repo = lambda _db, org: FakeTimelineRepo(store, org)  # type: ignore[method-assign]
    tag_mod.timeline_service = tls

    tags = TagService()
    tags._repo = lambda _db, org: FakeTagRepo(store, org)  # type: ignore[method-assign]

    def _fake_deal_repo(db: Any, *, organization_id: uuid.UUID):
        return FakeDealRepo(store, organization_id)

    # Package __init__ shadows submodule names — patch via sys.modules.
    tag_mod.deal_repository = _fake_deal_repo  # type: ignore[assignment]

    fields = CustomFieldService()
    fields._repo = lambda _db, org: FakeFieldRepo(store, org)  # type: ignore[method-assign]

    return tags, fields, tls


def _seed_deal(store: Store, org_id: uuid.UUID) -> CrmDeal:
    deal = CrmDeal(
        id=uuid.uuid4(),
        organization_id=org_id,
        pipeline_id=uuid.uuid4(),
        stage_id=uuid.uuid4(),
        title="Tagged deal",
        created_at=_now(),
        updated_at=_now(),
        custom_fields={},
    )
    store.deals[deal.id] = deal
    return deal


@pytest.mark.asyncio
async def test_tag_crud() -> None:
    store = Store()
    tags, _, _ = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()

    created = await tags.create_tag(
        db,  # type: ignore[arg-type]
        org,
        CrmTagCreate(name="Hot", color="#FF5733"),
    )
    assert created.name == "Hot"
    assert created.color == "#FF5733"

    listed = await tags.list_tags(db, org)  # type: ignore[arg-type]
    assert listed.total == 1

    updated = await tags.update_tag(
        db,  # type: ignore[arg-type]
        org,
        created.id,
        CrmTagUpdate(name="Warm"),
    )
    assert updated.name == "Warm"

    await tags.delete_tag(db, org, created.id)  # type: ignore[arg-type]
    with pytest.raises(TagServiceError) as exc:
        await tags.get_tag(db, org, created.id)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_attach_detach_tag_logs_timeline() -> None:
    store = Store()
    tags, _, timeline = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    actor = uuid.uuid4()
    deal = _seed_deal(store, org)

    tag = await tags.create_tag(db, org, CrmTagCreate(name="VIP"))  # type: ignore[arg-type]
    attached = await tags.attach_tag_to_deal(
        db,  # type: ignore[arg-type]
        org,
        deal.id,
        tag.id,
        actor_id=actor,
    )
    assert attached.id == tag.id
    assert (deal.id, tag.id) in store.deal_tags

    events = await timeline.get_events(db, org, deal_id=deal.id)  # type: ignore[arg-type]
    types = {e.event_type for e in events.items}
    assert "tag_added" in types
    added = next(e for e in events.items if e.event_type == "tag_added")
    assert added.actor_id == actor
    assert added.payload["tag_id"] == str(tag.id)

    await tags.remove_tag_from_deal(
        db,  # type: ignore[arg-type]
        org,
        deal.id,
        tag.id,
        actor_id=actor,
    )
    assert (deal.id, tag.id) not in store.deal_tags
    events2 = await timeline.get_events(db, org, deal_id=deal.id)  # type: ignore[arg-type]
    assert "tag_removed" in {e.event_type for e in events2.items}


@pytest.mark.asyncio
async def test_custom_field_crud_and_unique_key() -> None:
    store = Store()
    _, fields, _ = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()

    created = await fields.create_definition(
        db,  # type: ignore[arg-type]
        org,
        CrmCustomFieldCreate(
            entity_type=CrmEntityType.DEAL,
            field_key="utm_source",
            label="UTM Source",
            field_type=CrmFieldType.TEXT,
        ),
    )
    assert created.field_key == "utm_source"

    listed = await fields.list_definitions(
        db,  # type: ignore[arg-type]
        org,
        entity_type=CrmEntityType.DEAL,
    )
    assert listed.total == 1

    with pytest.raises(CustomFieldServiceError) as exc:
        await fields.create_definition(
            db,  # type: ignore[arg-type]
            org,
            CrmCustomFieldCreate(
                entity_type=CrmEntityType.DEAL,
                field_key="utm_source",
                label="Duplicate",
                field_type=CrmFieldType.TEXT,
            ),
        )
    assert exc.value.status_code == 409

    # Same key on another entity type is allowed
    other = await fields.create_definition(
        db,  # type: ignore[arg-type]
        org,
        CrmCustomFieldCreate(
            entity_type=CrmEntityType.CONTACT,
            field_key="utm_source",
            label="Contact UTM",
            field_type=CrmFieldType.TEXT,
        ),
    )
    assert other.entity_type == CrmEntityType.CONTACT

    await fields.delete_definition(db, org, created.id)  # type: ignore[arg-type]
    remaining = await fields.list_definitions(db, org, entity_type=CrmEntityType.DEAL)  # type: ignore[arg-type]
    assert remaining.total == 0


def test_migration_033_exists() -> None:
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "033_crm_tags_custom_fields.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "crm_tags" in text
    assert "crm_deal_tags" in text
    assert "crm_custom_field_defs" in text
    assert "uq_crm_field_def_key" in text
    assert "032_crm_activities_notes_timeline" in text
    assert 'ondelete="CASCADE"' in text


def test_no_direct_selects_outside_repos() -> None:
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    pattern = re.compile(r"select\(\s*Crm(Tag|CustomFieldDefinition)\b")
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


def test_deal_tags_relationship_configured() -> None:
    from app.models.crm.deal import CrmDeal
    from app.models.crm.tag import CrmTag, crm_deal_tags

    assert CrmDeal.tags.property.secondary is crm_deal_tags
    assert CrmTag.deals.property.secondary is crm_deal_tags
