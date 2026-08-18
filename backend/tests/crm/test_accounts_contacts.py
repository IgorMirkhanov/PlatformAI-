"""Native CRM Phase A step 2 — accounts / contacts + client auto-capture."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.accounts import router as crm_accounts_router
from app.api.endpoints.crm.contacts import router as crm_contacts_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import Bot, Client, PlatformType, UserRole
from app.models.crm.account import CrmAccount
from app.models.crm.contact import CrmContact
from app.models.users import User
from app.schemas.crm.accounts_contacts import (
    CrmAccountCreate,
    CrmAccountUpdate,
    CrmContactCreate,
)
from app.services.crm.account_service import AccountService, AccountServiceError
from app.services.crm.contact_service import ContactService, ContactServiceError


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


class CrmStore:
    def __init__(self) -> None:
        self.accounts: dict[uuid.UUID, CrmAccount] = {}
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.clients: dict[uuid.UUID, Client] = {}
        self.bots: dict[uuid.UUID, Bot] = {}


class FakeAccountRepo:
    def __init__(self, store: CrmStore, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmAccount) -> CrmAccount:
        entity.organization_id = self.organization_id
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.accounts[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmAccount | None:
        row = self.store.accounts.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def list_filtered(
        self, *, q: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[CrmAccount]:
        rows = [a for a in self.store.accounts.values() if a.organization_id == self.organization_id]
        if q:
            needle = q.lower()
            rows = [
                a
                for a in rows
                if needle in (a.name or "").lower()
                or needle in (a.industry or "").lower()
                or needle in (a.website or "").lower()
            ]
        rows = sorted(rows, key=lambda a: a.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def count_filtered(self, *, q: str | None = None) -> int:
        return len(await self.list_filtered(q=q, limit=10_000, offset=0))

    async def delete(self, entity: CrmAccount) -> None:
        self.store.accounts.pop(entity.id, None)


class FakeContactRepo:
    def __init__(self, store: CrmStore, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmContact) -> CrmContact:
        entity.organization_id = self.organization_id
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        if entity.linked_client_id is not None:
            for other in self.store.contacts.values():
                if other.linked_client_id == entity.linked_client_id and other.id != entity.id:
                    raise ValueError("duplicate linked_client_id")
        self.store.contacts[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmContact | None:
        row = self.store.contacts.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_by_linked_client_id(self, client_id: uuid.UUID) -> CrmContact | None:
        for row in self.store.contacts.values():
            if row.organization_id == self.organization_id and row.linked_client_id == client_id:
                return row
        return None

    async def list_filtered(
        self,
        *,
        q: str | None = None,
        account_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrmContact]:
        rows = [c for c in self.store.contacts.values() if c.organization_id == self.organization_id]
        if account_id is not None:
            rows = [c for c in rows if c.account_id == account_id]
        if q:
            needle = q.lower()
            rows = [
                c
                for c in rows
                if needle in (c.first_name or "").lower()
                or needle in (c.last_name or "").lower()
                or needle in (c.email or "").lower()
                or needle in (c.phone or "").lower()
            ]
        rows = sorted(rows, key=lambda c: c.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def count_filtered(
        self, *, q: str | None = None, account_id: uuid.UUID | None = None
    ) -> int:
        return len(
            await self.list_filtered(q=q, account_id=account_id, limit=10_000, offset=0)
        )

    async def delete(self, entity: CrmContact) -> None:
        self.store.contacts.pop(entity.id, None)


class CaptureSession:
    """Session stand-in for get_or_create_from_client Client+Bot load."""

    def __init__(self, store: CrmStore) -> None:
        self.store = store

    async def flush(self) -> None:
        return None

    async def execute(self, _stmt: Any) -> Any:
        # Always return the single client registered for capture tests.
        clients = list(self.store.clients.values())
        client = clients[0] if clients else None
        if client is not None and client.bot_id in self.store.bots:
            client.bot = self.store.bots[client.bot_id]
        return SimpleNamespace(scalar_one_or_none=lambda: client)


def _bind_account_service(store: CrmStore) -> AccountService:
    service = AccountService()

    def _repo(_db: Any, organization_id: uuid.UUID) -> FakeAccountRepo:
        return FakeAccountRepo(store, organization_id)

    service._repo = _repo  # type: ignore[method-assign]
    return service


def _bind_contact_service(store: CrmStore) -> ContactService:
    service = ContactService()

    def _contacts(_db: Any, organization_id: uuid.UUID) -> FakeContactRepo:
        return FakeContactRepo(store, organization_id)

    def _accounts(_db: Any, organization_id: uuid.UUID) -> FakeAccountRepo:
        return FakeAccountRepo(store, organization_id)

    service._contacts = _contacts  # type: ignore[method-assign]
    service._accounts = _accounts  # type: ignore[method-assign]
    return service


@pytest.mark.asyncio
async def test_account_crud_scoped() -> None:
    store = CrmStore()
    service = _bind_account_service(store)
    db = CaptureSession(store)
    org = uuid.uuid4()

    created = await service.create_account(
        db, org, CrmAccountCreate(name="Acme LLC", industry="Logistics")  # type: ignore[arg-type]
    )
    assert created.organization_id == org
    listed = await service.list_accounts(db, org, q="Acme")  # type: ignore[arg-type]
    assert listed.total == 1
    assert listed.items[0].id == created.id

    updated = await service.update_account(
        db, org, created.id, CrmAccountUpdate(website="https://acme.test")  # type: ignore[arg-type]
    )
    assert updated.website == "https://acme.test"

    await service.delete_account(db, org, created.id)  # type: ignore[arg-type]
    with pytest.raises(AccountServiceError) as exc:
        await service.get_account(db, org, created.id)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_contact_crud_scoped() -> None:
    store = CrmStore()
    accounts = _bind_account_service(store)
    contacts = _bind_contact_service(store)
    db = CaptureSession(store)
    org = uuid.uuid4()

    account = await accounts.create_account(
        db, org, CrmAccountCreate(name="Buyer Co")  # type: ignore[arg-type]
    )
    created = await contacts.create_contact(
        db,  # type: ignore[arg-type]
        org,
        CrmContactCreate(first_name="Ada", last_name="Lovelace", account_id=account.id, email="ada@example.com"),
    )
    assert created.organization_id == org
    assert created.account_id == account.id

    listed = await contacts.list_contacts(db, org, q="Ada")  # type: ignore[arg-type]
    assert listed.total == 1


@pytest.mark.asyncio
async def test_get_or_create_from_client_idempotent() -> None:
    store = CrmStore()
    service = _bind_contact_service(store)
    db = CaptureSession(store)

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    client_id = uuid.uuid4()

    bot = Bot(
        id=bot_id,
        user_id=user_id,
        organization_id=org_id,
        name="Support Bot",
        platform_type=PlatformType.WHATSAPP,
        is_active=True,
        credentials={},
    )
    client = Client(
        id=client_id,
        bot_id=bot_id,
        external_id="77001234567",
        username="ada",
        first_name="Ada",
        current_step_id="",
        is_paused_by_operator=False,
    )
    client.bot = bot
    store.bots[bot_id] = bot
    store.clients[client_id] = client

    first = await service.get_or_create_from_client(db, client_id)  # type: ignore[arg-type]
    second = await service.get_or_create_from_client(db, client_id)  # type: ignore[arg-type]

    assert first.id == second.id
    assert first.organization_id == org_id
    assert first.linked_client_id == client_id
    assert first.first_name == "Ada"
    assert first.source == "whatsapp"
    assert len(store.contacts) == 1


@pytest.mark.asyncio
async def test_get_or_create_requires_bot_organization() -> None:
    store = CrmStore()
    service = _bind_contact_service(store)
    db = CaptureSession(store)

    bot_id = uuid.uuid4()
    client_id = uuid.uuid4()
    bot = Bot(
        id=bot_id,
        user_id=uuid.uuid4(),
        organization_id=None,
        name="Orphan Bot",
        platform_type=PlatformType.TELEGRAM,
        is_active=True,
        credentials={},
    )
    client = Client(
        id=client_id,
        bot_id=bot_id,
        external_id="1",
        username="",
        first_name="X",
        current_step_id="",
        is_paused_by_operator=False,
    )
    client.bot = bot
    store.bots[bot_id] = bot
    store.clients[client_id] = client

    with pytest.raises(ContactServiceError) as exc:
        await service.get_or_create_from_client(db, client_id)  # type: ignore[arg-type]
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_tenant_isolation_accounts_and_contacts() -> None:
    store = CrmStore()
    accounts = _bind_account_service(store)
    contacts = _bind_contact_service(store)
    db = CaptureSession(store)
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    acc_a = await accounts.create_account(
        db, org_a, CrmAccountCreate(name="A Only")  # type: ignore[arg-type]
    )
    await contacts.create_contact(
        db, org_a, CrmContactCreate(first_name="Alice")  # type: ignore[arg-type]
    )

    listed_b_acc = await accounts.list_accounts(db, org_b)  # type: ignore[arg-type]
    listed_b_ct = await contacts.list_contacts(db, org_b)  # type: ignore[arg-type]
    assert listed_b_acc.total == 0
    assert listed_b_ct.total == 0

    with pytest.raises(AccountServiceError) as exc:
        await accounts.get_account(db, org_b, acc_a.id)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_cross_tenant_account_404(monkeypatch: pytest.MonkeyPatch) -> None:
    store = CrmStore()
    service = _bind_account_service(store)
    db = CaptureSession(store)
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    acc = await service.create_account(
        db, org_a, CrmAccountCreate(name="Secret")  # type: ignore[arg-type]
    )
    user_b = _make_user(org_id=org_b)

    monkeypatch.setattr("app.api.endpoints.crm.accounts.account_service", service)

    app = FastAPI()
    app.include_router(crm_accounts_router, prefix="/api/v1")
    app.include_router(crm_contacts_router, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user_b

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/crm/accounts/{acc.id}")
        listed = await client.get("/api/v1/crm/accounts")

    assert response.status_code == 404
    assert listed.status_code == 200
    assert listed.json()["total"] == 0


def test_migration_030_accounts_contacts() -> None:
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "030_crm_accounts_contacts.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "crm_accounts" in text
    assert "crm_contacts" in text
    assert "uq_crm_contacts_linked_client_id" in text
    assert "029_crm_pipelines_stages" in text
    assert "clients.id" in text


def test_no_direct_crm_account_contact_selects_outside_repos() -> None:
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    pattern = re.compile(r"select\(\s*Crm(Account|Contact)\b")
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
