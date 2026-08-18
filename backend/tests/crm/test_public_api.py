"""Native CRM — public API keys + inbound leads."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.api_keys import router as api_keys_router
from app.api.endpoints.crm.deps import require_crm_deal_admin, verify_crm_api_key
from app.api.endpoints.crm.public_webhooks import router as public_leads_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.crm.api_key import CrmApiKey
from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.users import User
from app.schemas.crm.api_keys import CrmApiKeyCreate, InboundLeadCreate
from app.services.crm.api_key_service import (
    ApiKeyService,
    api_key_display_prefix,
    generate_raw_api_key,
    hash_api_key,
)
from app.services.crm.inbound_lead_service import InboundLeadService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_admin(org_id: uuid.UUID) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@crm.test",
        hashed_password="!",
        company_name="Org",
        full_name="Admin",
        company_id=org_id,
        role=UserRole.ADMIN,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


class Store:
    def __init__(self) -> None:
        self.keys: dict[uuid.UUID, CrmApiKey] = {}
        self.keys_by_hash: dict[str, CrmApiKey] = {}
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}


class FlushSession:
    async def flush(self) -> None:
        return None

    async def scalar(self, _stmt: Any) -> Any:
        return None


class FakeApiKeyRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmApiKey) -> CrmApiKey:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        self.store.keys[entity.id] = entity
        self.store.keys_by_hash[entity.key_hash] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmApiKey | None:
        row = self.store.keys.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def list_ordered(self, *, limit: int = 100, offset: int = 0) -> list[CrmApiKey]:
        rows = [
            k for k in self.store.keys.values() if k.organization_id == self.organization_id
        ]
        rows = sorted(rows, key=lambda k: k.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def count_all(self) -> int:
        return len(
            [k for k in self.store.keys.values() if k.organization_id == self.organization_id]
        )

    async def delete(self, entity: CrmApiKey) -> None:
        self.store.keys.pop(entity.id, None)
        self.store.keys_by_hash.pop(entity.key_hash, None)

    async def touch_last_used(self, entity: CrmApiKey) -> None:
        entity.last_used_at = _now()


class FakeContactRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmContact) -> CrmContact:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.contacts[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmContact | None:
        row = self.store.contacts.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def find_by_phone_or_email(
        self, *, phone: str | None = None, email: str | None = None
    ) -> CrmContact | None:
        phone_n = (phone or "").strip() or None
        email_n = (email or "").strip() or None
        for c in self.store.contacts.values():
            if c.organization_id != self.organization_id:
                continue
            if phone_n and c.phone == phone_n:
                return c
            if email_n and (c.email or "").lower() == email_n.lower():
                return c
        return None


class FakePipelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_with_stages(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        row.stages = [
            s
            for s in self.store.stages.values()
            if s.pipeline_id == pipeline_id and s.organization_id == self.organization_id
        ]
        return row

    async def get_default(self) -> CrmPipeline | None:
        for p in self.store.pipelines.values():
            if p.organization_id == self.organization_id and p.is_default:
                return await self.get_with_stages(p.id)
        return None

    async def list_with_stages(self, *, limit: int = 100) -> list[CrmPipeline]:
        rows = [
            p for p in self.store.pipelines.values() if p.organization_id == self.organization_id
        ]
        out = []
        for p in rows[:limit]:
            out.append(await self.get_with_stages(p.id))
        return [p for p in out if p is not None]


class FakeDealRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmDeal) -> CrmDeal:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
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
        return await self.get(deal_id)

    async def get_with_relations_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get(deal_id)

    async def get_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get(deal_id)


class FakeStageRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
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


class FakeAccountRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, _account_id: uuid.UUID) -> Any:
        return None


def _seed_pipeline(store: Store, org: uuid.UUID) -> tuple[CrmPipeline, CrmStage]:
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
    store.pipelines[pipeline.id] = pipeline
    store.stages[stage.id] = stage
    return pipeline, stage


def _bind(store: Store) -> tuple[ApiKeyService, InboundLeadService]:
    import sys

    from app.services.crm.contact_service import ContactService
    from app.services.crm.deal_service import DealService

    keys = ApiKeyService()
    keys._repo = lambda _db, org: FakeApiKeyRepo(store, org)  # type: ignore[method-assign]

    async def _get_by_hash(_db: Any, digest: str):
        row = store.keys_by_hash.get(digest)
        if row is None or not row.is_active:
            return None
        return row

    key_mod = sys.modules["app.services.crm.api_key_service"]
    key_mod.get_active_api_key_by_hash = _get_by_hash  # type: ignore[assignment]
    key_mod.api_key_repository = (  # type: ignore[assignment]
        lambda db, *, organization_id: FakeApiKeyRepo(store, organization_id)
    )

    contacts = ContactService()
    contacts._contacts = lambda _db, org: FakeContactRepo(store, org)  # type: ignore[method-assign]
    contacts._accounts = lambda _db, org: FakeAccountRepo(store, org)  # type: ignore[method-assign]
    contact_mod = sys.modules["app.services.crm.contact_service"]
    contact_mod.contact_service = contacts
    contact_mod.contact_repository = (  # type: ignore[assignment]
        lambda db, *, organization_id: FakeContactRepo(store, organization_id)
    )

    deals = DealService()
    deals._deals = lambda _db, org, **_kw: FakeDealRepo(store, org)  # type: ignore[method-assign]
    deals._pipelines = lambda _db, org: FakePipelineRepo(store, org)  # type: ignore[method-assign]
    deals._stages = lambda _db, org: FakeStageRepo(store, org)  # type: ignore[method-assign]
    deals._contacts = lambda _db, org: FakeContactRepo(store, org)  # type: ignore[method-assign]
    deals._accounts = lambda _db, org: FakeAccountRepo(store, org)  # type: ignore[method-assign]

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    deals._log_event = _noop  # type: ignore[method-assign]
    deals._dispatch_automations = _noop  # type: ignore[method-assign]
    deal_mod = sys.modules["app.services.crm.deal_service"]
    deal_mod.deal_service = deals

    inbound_mod = sys.modules["app.services.crm.inbound_lead_service"]
    inbound_mod.contact_repository = (  # type: ignore[assignment]
        lambda db, *, organization_id: FakeContactRepo(store, organization_id)
    )
    inbound_mod.pipeline_repository = (  # type: ignore[assignment]
        lambda db, *, organization_id: FakePipelineRepo(store, organization_id)
    )
    inbound_mod.contact_service = contacts
    inbound_mod.deal_service = deals

    inbound = InboundLeadService()
    return keys, inbound


def test_raw_key_never_equals_stored_hash() -> None:
    raw = generate_raw_api_key()
    assert raw.startswith("mpai_crm_")
    digest = hash_api_key(raw)
    assert digest != raw
    assert len(digest) == 64
    assert api_key_display_prefix(raw) == raw[:16]
    assert raw not in digest


@pytest.mark.asyncio
async def test_admin_creates_api_key_returns_raw_once() -> None:
    store = Store()
    keys, _ = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()

    created = await keys.create_api_key(
        db,  # type: ignore[arg-type]
        org,
        CrmApiKeyCreate(label="Tilda Landing"),
        created_by_id=uuid.uuid4(),
    )
    assert created.api_key.startswith("mpai_crm_")
    assert created.key_prefix == created.api_key[:16]
    assert created.label == "Tilda Landing"

    listed = await keys.list_keys(db, org)  # type: ignore[arg-type]
    assert listed.total == 1
    assert not hasattr(listed.items[0], "api_key") or "api_key" not in listed.items[0].model_dump()
    stored = next(iter(store.keys.values()))
    assert stored.key_hash == hash_api_key(created.api_key)
    assert stored.key_hash != created.api_key


@pytest.mark.asyncio
async def test_inbound_lead_rejects_bad_key() -> None:
    store = Store()
    keys, inbound = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    _seed_pipeline(store, org)
    await keys.create_api_key(db, org, CrmApiKeyCreate(label="Web"))  # type: ignore[arg-type]

    app = FastAPI()
    app.include_router(public_leads_router, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    # Use real verify against our patched service store
    import sys

    sys.modules["app.services.crm.api_key_service"].api_key_service = keys

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/crm/public/leads",
            json={"first_name": "Ada", "email": "ada@example.com"},
            headers={"X-CRM-API-Key": "mpai_crm_invalid_key_value_xxxxx"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_inbound_lead_success_creates_contact_and_deal() -> None:
    store = Store()
    keys, inbound = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    _seed_pipeline(store, org)

    created_key = await keys.create_api_key(
        db,  # type: ignore[arg-type]
        org,
        CrmApiKeyCreate(label="Forms"),
    )

    result = await inbound.ingest(
        db,  # type: ignore[arg-type]
        org,
        InboundLeadCreate(
            first_name="Ada",
            email="ada@example.com",
            phone="+77001112233",
            deal_title="Landing lead",
            source="tilda",
        ),
    )
    assert result.organization_id == org
    assert result.contact_created is True
    assert result.deal_title == "Landing lead"

    contact = store.contacts[result.contact_id]
    deal = store.deals[result.deal_id]
    assert contact.organization_id == org
    assert contact.email == "ada@example.com"
    assert deal.organization_id == org
    assert deal.contact_id == contact.id
    assert deal.source == "tilda"

    # Verify key works via service
    verified = await keys.verify_raw_key(db, created_key.api_key)  # type: ignore[arg-type]
    assert verified is not None
    assert verified.organization_id == org


@pytest.mark.asyncio
async def test_api_key_management_and_public_http(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    keys, inbound = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    _seed_pipeline(store, org)
    admin = _make_admin(org)

    monkeypatch.setattr("app.api.endpoints.crm.api_keys.api_key_service", keys)
    monkeypatch.setattr("app.api.endpoints.crm.public_webhooks.inbound_lead_service", inbound)
    monkeypatch.setattr("app.api.endpoints.crm.deps.api_key_service", keys)

    app = FastAPI()
    app.include_router(api_keys_router, prefix="/api/v1")
    app.include_router(public_leads_router, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_crm_deal_admin] = lambda: admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/crm/api-keys",
            json={"label": "Tilda Landing Page"},
        )
        assert created.status_code == 201
        body = created.json()
        raw = body["api_key"]
        assert raw.startswith("mpai_crm_")
        assert "key_hash" not in body

        listed = await client.get("/api/v1/crm/api-keys")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert "api_key" not in listed.json()["items"][0]

        bad = await client.post(
            "/api/v1/crm/public/leads",
            json={"first_name": "X", "email": "x@test.com"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert bad.status_code == 401

        ok = await client.post(
            "/api/v1/crm/public/leads",
            json={
                "first_name": "Grace",
                "email": "grace@example.com",
                "deal_title": "From API",
            },
            headers={"X-CRM-API-Key": raw},
        )
        assert ok.status_code == 201
        payload = ok.json()
        assert payload["organization_id"] == str(org)
        assert uuid.UUID(payload["contact_id"]) in store.contacts
        assert uuid.UUID(payload["deal_id"]) in store.deals
        assert store.deals[uuid.UUID(payload["deal_id"])].organization_id == org


def test_migration_036_exists() -> None:
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "036_crm_api_keys.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "crm_api_keys" in text
    assert "035_crm_automation_rules" in text
    assert "key_hash" in text
    assert "key_prefix" in text
    assert 'ondelete="CASCADE"' in text
