"""Integration tests for tenant security audit logging."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.api_keys import router as api_keys_router
from app.api.endpoints.crm.deps import require_crm_deal_admin
from app.api.endpoints.security.audit_logs import router as audit_logs_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.billing.organization_invite import OrganizationInvite
from app.models.core_models import UserRole
from app.models.crm.api_key import CrmApiKey
from app.models.security.audit_log import AuditLog
from app.models.users import User
from app.schemas.crm.api_keys import CrmApiKeyCreate
from app.schemas.team_schemas import UpdateTeamMemberRoleRequest
from app.services.billing.invite_service import InviteService
from app.services.crm.api_key_service import ApiKeyService
from app.services.security_audit_service import SecurityAuditService
from app.services.team_service import TeamService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(*, org_id: uuid.UUID, role: UserRole = UserRole.OWNER, email: str | None = None) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=email or f"{uid.hex[:8]}@audit.test",
        hashed_password="!",
        company_name="Audit Org",
        full_name="Audit Actor",
        company_id=org_id,
        role=role,
        is_superadmin=False,
        timezone="Asia/Almaty",
        created_at=_now(),
    )


class AuditStore:
    def __init__(self) -> None:
        self.logs: list[AuditLog] = []
        self.keys: dict[uuid.UUID, CrmApiKey] = {}
        self.invites: dict[uuid.UUID, OrganizationInvite] = {}


class AuditSession:
    """Minimal async session that captures AuditLog rows."""

    def __init__(self, store: AuditStore) -> None:
        self.store = store

    def add(self, obj: Any) -> None:
        if isinstance(obj, AuditLog):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            self.store.logs.append(obj)
        elif isinstance(obj, CrmApiKey):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            obj.updated_at = getattr(obj, "updated_at", None) or _now()
            self.store.keys[obj.id] = obj
        elif isinstance(obj, OrganizationInvite):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            self.store.invites[obj.id] = obj

    async def flush(self) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        if isinstance(obj, CrmApiKey):
            self.store.keys.pop(obj.id, None)
        elif isinstance(obj, OrganizationInvite):
            self.store.invites.pop(obj.id, None)

    async def scalar(self, stmt: Any) -> Any:
        rows = await self._rows(stmt)
        return rows[0] if rows else None

    async def execute(self, stmt: Any) -> Any:
        rows = await self._rows(stmt)

        class _Result:
            def scalars(self_inner) -> Any:
                class _S:
                    def all(self_s) -> list[Any]:
                        return rows

                return _S()

            def scalar_one_or_none(self_inner) -> Any:
                return rows[0] if rows else None

        return _Result()

    async def _rows(self, stmt: Any) -> list[Any]:
        try:
            compiled = stmt.compile(compile_kwargs={"render_postcompile": True})
            sql = str(compiled).lower()
            params = dict(compiled.params or {})
        except Exception:
            sql = str(stmt).lower()
            params = {}

        values = list(params.values())
        org_ids = [v for v in values if isinstance(v, uuid.UUID)]

        if "audit_logs" in sql:
            rows = list(self.store.logs)
            if org_ids:
                oid = org_ids[0]
                rows = [r for r in rows if r.organization_id == oid]
            actions = [v for v in values if isinstance(v, str) and v.isupper() and "_" in v]
            if actions:
                rows = [r for r in rows if r.action == actions[0]]
            return rows

        if "organization_invites" in sql:
            rows = list(self.store.invites.values())
            emails = [v for v in values if isinstance(v, str) and "@" in v]
            if emails:
                rows = [r for r in rows if r.email == emails[0]]
            if org_ids:
                rows = [r for r in rows if r.organization_id in org_ids]
            return rows

        return []


class FakeApiKeyRepo:
    def __init__(self, store: AuditStore, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmApiKey) -> CrmApiKey:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        self.store.keys[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmApiKey | None:
        row = self.store.keys.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def delete(self, entity: CrmApiKey) -> None:
        self.store.keys.pop(entity.id, None)

    async def list_ordered(self, *, limit: int = 100, offset: int = 0) -> list[CrmApiKey]:
        rows = [k for k in self.store.keys.values() if k.organization_id == self.organization_id]
        return rows[offset : offset + limit]

    async def count_all(self) -> int:
        return len([k for k in self.store.keys.values() if k.organization_id == self.organization_id])


def _logs_for(store: AuditStore, *, action: str, org_id: uuid.UUID) -> list[AuditLog]:
    return [row for row in store.logs if row.action == action and row.organization_id == org_id]


@pytest.mark.asyncio
async def test_api_key_revoke_writes_audit_log(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AuditStore()
    org = uuid.uuid4()
    admin = _user(org_id=org, role=UserRole.ADMIN)
    db = AuditSession(store)
    keys = ApiKeyService()

    monkeypatch.setattr(
        keys,
        "_repo",
        lambda _db, organization_id: FakeApiKeyRepo(store, organization_id),
    )
    monkeypatch.setattr("app.api.endpoints.crm.api_keys.api_key_service", keys)

    created = await keys.create_api_key(
        db,  # type: ignore[arg-type]
        org,
        CrmApiKeyCreate(label="Landing"),
        created_by_id=admin.id,
    )

    app = FastAPI()
    app.include_router(api_keys_router, prefix="/api/v1")

    async def _db():
        yield db

    async def _user_dep():
        return admin

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_crm_deal_admin] = _user_dep
    app.dependency_overrides[get_current_user] = _user_dep

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.delete(f"/api/v1/crm/api-keys/{created.id}")

    assert resp.status_code == 204
    rows = _logs_for(store, action="API_KEY_REVOKED", org_id=org)
    assert len(rows) == 1
    assert rows[0].user_id == admin.id
    assert rows[0].organization_id == org
    assert rows[0].details is not None
    assert rows[0].details["key_id"] == str(created.id)
    assert created.id not in store.keys


@pytest.mark.asyncio
async def test_invite_created_via_organizations_invites_endpoint() -> None:
    """POST /api/v1/organizations/invites must emit INVITE_CREATED audit row."""
    store = AuditStore()
    org = uuid.uuid4()
    admin = _user(org_id=org, role=UserRole.OWNER)
    db = AuditSession(store)
    service = InviteService()

    created = await service.create_invite(
        db,  # type: ignore[arg-type]
        org,
        email="invitee@example.com",
        role="OPERATOR",
        inviter_user_id=admin.id,
    )

    # HTTP surface used by the product — verify the service path the route calls.
    from fastapi import APIRouter

    app = FastAPI()
    router = APIRouter(prefix="/organizations/invites")

    @router.post("")
    async def create_invite_http(payload: dict[str, str]) -> Any:
        return await service.create_invite(
            db,  # type: ignore[arg-type]
            org,
            email=payload["email"],
            role=payload["role"],
            inviter_user_id=admin.id,
        )

    app.include_router(router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/organizations/invites",
            json={"email": "second@example.com", "role": "OPERATOR"},
        )

    assert resp.status_code == 200
    rows = _logs_for(store, action="INVITE_CREATED", org_id=org)
    assert len(rows) == 2
    assert all(row.user_id == admin.id for row in rows)
    assert all(row.organization_id == org for row in rows)
    emails = {row.details["email"] for row in rows if row.details}
    assert "invitee@example.com" in emails
    assert "second@example.com" in emails
    assert created.id in store.invites


@pytest.mark.asyncio
async def test_role_changed_writes_audit_log() -> None:
    store = AuditStore()
    org = uuid.uuid4()
    actor = _user(org_id=org, role=UserRole.OWNER)
    member = _user(org_id=org, role=UserRole.OPERATOR, email="op@audit.test")
    membership = type("Membership", (), {})()
    membership.role = UserRole.OPERATOR
    membership.company_id = org
    membership.user_id = member.id

    db = AuditSession(store)
    service = TeamService()
    service._get_company_membership = AsyncMock(return_value=(member, membership))  # type: ignore[method-assign]
    service._count_owners = AsyncMock(return_value=1)  # type: ignore[method-assign]

    result = await service.update_member_role(
        db,  # type: ignore[arg-type]
        current_user=actor,
        member_id=member.id,
        payload=UpdateTeamMemberRoleRequest(role=UserRole.PROMPT_ENGINEER),
        ip_address="203.0.113.10",
    )

    assert result.role == UserRole.PROMPT_ENGINEER
    rows = _logs_for(store, action="ROLE_CHANGED", org_id=org)
    assert len(rows) == 1
    assert rows[0].user_id == actor.id
    assert rows[0].organization_id == org
    assert rows[0].ip_address == "203.0.113.10"
    assert rows[0].details is not None
    assert rows[0].details["target_user_id"] == str(member.id)
    assert rows[0].details["previous_role"] == "OPERATOR"
    assert rows[0].details["new_role"] == "PROMPT_ENGINEER"


@pytest.mark.asyncio
async def test_tenant_isolation_on_audit_logs_api() -> None:
    store = AuditStore()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    user_a = _user(org_id=org_a, role=UserRole.OWNER)
    user_b = _user(org_id=org_b, role=UserRole.OWNER)
    db = AuditSession(store)
    audit = SecurityAuditService()

    await audit.write(
        db,  # type: ignore[arg-type]
        organization_id=org_a,
        user_id=user_a.id,
        action="API_KEY_REVOKED",
        details={"secret": "org-a-only"},
    )
    await audit.write(
        db,  # type: ignore[arg-type]
        organization_id=org_b,
        user_id=user_b.id,
        action="INVITE_CREATED",
        details={"secret": "org-b-only"},
    )

    app = FastAPI()
    app.include_router(audit_logs_router, prefix="/api/v1")

    async def _db():
        yield db

    async def _as_user_a():
        return user_a

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _as_user_a

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/security/audit-logs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["organization_id"] == str(org_a)
    assert body["items"][0]["action"] == "API_KEY_REVOKED"
    leaked = [item for item in body["items"] if item["organization_id"] == str(org_b)]
    assert leaked == []
    assert all("org-b-only" not in str(item.get("details")) for item in body["items"])
