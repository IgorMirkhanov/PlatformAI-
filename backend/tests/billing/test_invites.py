"""Organization invite tests — create/accept, expiry, tenant isolation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.billing.invites import router as invites_router
from app.core.database import get_db
from app.core.rbac import (
    Permission,
    can_manage_billing,
    can_manage_crm,
    can_manage_flows,
    can_manage_settings,
    get_current_user,
)
from app.models.billing.organization_invite import OrganizationInvite
from app.models.core_models import UserCompanyWorkspace, UserRole
from app.models.users import User
from app.services.billing import invite_service as invite_mod
from app.services.billing.invite_service import (
    InviteExpiredError,
    InviteService,
    hash_invite_token,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(*, org_id: uuid.UUID, role: UserRole, email: str | None = None) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=email or f"{uid.hex[:8]}@invite.test",
        hashed_password="!",
        company_name="Org",
        full_name="Invite Tester",
        company_id=org_id,
        role=role,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


class Store:
    def __init__(self) -> None:
        self.invites: dict[uuid.UUID, OrganizationInvite] = {}
        self.memberships: dict[tuple[uuid.UUID, uuid.UUID], UserCompanyWorkspace] = {}


class FakeSession:
    """Minimal async session for invite service unit tests."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, obj: Any) -> None:
        if isinstance(obj, OrganizationInvite):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            self.store.invites[obj.id] = obj
        elif isinstance(obj, UserCompanyWorkspace):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            self.store.memberships[(obj.user_id, obj.company_id)] = obj

    async def flush(self) -> None:
        return None

    async def delete(self, obj: Any) -> None:
        if isinstance(obj, OrganizationInvite):
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

        return _Result()

    async def _rows(self, stmt: Any) -> list[Any]:
        # Inspect compiled SQL text + params for the small invite query surface.
        try:
            compiled = stmt.compile(compile_kwargs={"render_postcompile": True})
            sql = str(compiled).lower()
            params = dict(compiled.params or {})
        except Exception:
            sql = str(stmt).lower()
            params = {}

        values = list(params.values())

        if "user_company_workspaces" in sql:
            user_id = next((v for v in values if isinstance(v, uuid.UUID)), None)
            company_id = None
            uuids = [v for v in values if isinstance(v, uuid.UUID)]
            if len(uuids) >= 2:
                user_id, company_id = uuids[0], uuids[1]
            elif len(uuids) == 1:
                user_id = uuids[0]
            out = []
            for m in self.store.memberships.values():
                if user_id is not None and m.user_id != user_id:
                    continue
                if company_id is not None and m.company_id != company_id:
                    continue
                out.append(m)
            return out

        # organization_invites queries
        rows = list(self.store.invites.values())
        token_hashes = [v for v in values if isinstance(v, str) and len(v) == 64]
        emails = [v for v in values if isinstance(v, str) and "@" in v]
        org_ids = [v for v in values if isinstance(v, uuid.UUID)]
        invite_ids = [v for v in values if isinstance(v, uuid.UUID)]
        bools = [v for v in values if isinstance(v, bool)]

        if token_hashes:
            th = token_hashes[0]
            rows = [r for r in rows if r.token_hash == th]
            return rows

        if "organization_invites.id" in sql or (
            "organization_invites" in sql and "id" in sql and len(invite_ids) >= 2
        ):
            # revoke: id + organization_id
            if len(org_ids) >= 2:
                iid, oid = org_ids[0], org_ids[1]
                rows = [r for r in rows if r.id == iid and r.organization_id == oid]
            elif len(org_ids) == 1:
                rows = [r for r in rows if r.id == org_ids[0] or r.organization_id == org_ids[0]]
            return rows

        if emails and org_ids:
            email = emails[0]
            oid = org_ids[0]
            now = _now()
            rows = [
                r
                for r in rows
                if r.organization_id == oid
                and r.email == email
                and not r.is_accepted
                and r.expires_at > now
            ]
            return rows

        if org_ids and "expires_at" in sql:
            oid = org_ids[0]
            now = _now()
            rows = [
                r
                for r in rows
                if r.organization_id == oid and not r.is_accepted and r.expires_at > now
            ]
            return rows

        if org_ids:
            oid = org_ids[0]
            rows = [r for r in rows if r.organization_id == oid]
            if bools:
                rows = [r for r in rows if r.is_accepted is bools[0]]
            return rows

        return rows


@pytest.mark.asyncio
async def test_create_and_accept_invite_adds_membership() -> None:
    store = Store()
    db = FakeSession(store)
    org_id = uuid.uuid4()
    owner = _user(org_id=org_id, role=UserRole.OWNER, email="owner@a.test")
    service = InviteService()

    created = await service.create_invite(
        db,  # type: ignore[arg-type]
        org_id,
        email="member@a.test",
        role="MEMBER",
        inviter_user_id=owner.id,
    )
    assert created.token
    assert created.role == "MEMBER"
    stored = next(iter(store.invites.values()))
    assert stored.token_hash == hash_invite_token(created.token)
    assert stored.token_hash != created.token

    invitee = _user(org_id=uuid.uuid4(), role=UserRole.OPERATOR, email="member@a.test")
    accepted = await service.accept_invite(db, created.token, invitee)  # type: ignore[arg-type]
    assert accepted.organization_id == org_id
    assert accepted.role == "MEMBER"
    assert (invitee.id, org_id) in store.memberships
    assert store.memberships[(invitee.id, org_id)].role == UserRole.MEMBER
    assert invitee.company_id == org_id
    assert invitee.role == UserRole.MEMBER
    assert next(iter(store.invites.values())).is_accepted is True


@pytest.mark.asyncio
async def test_accept_expired_invite_rejected() -> None:
    store = Store()
    db = FakeSession(store)
    org_id = uuid.uuid4()
    owner = _user(org_id=org_id, role=UserRole.OWNER)
    service = InviteService()

    created = await service.create_invite(
        db,  # type: ignore[arg-type]
        org_id,
        email="late@a.test",
        role="OPERATOR",
        inviter_user_id=owner.id,
    )
    invite = next(iter(store.invites.values()))
    invite.expires_at = _now() - timedelta(hours=1)

    invitee = _user(org_id=uuid.uuid4(), role=UserRole.OPERATOR, email="late@a.test")
    with pytest.raises(InviteExpiredError):
        await service.accept_invite(db, created.token, invitee)  # type: ignore[arg-type]

    assert invite.is_accepted is False
    assert (invitee.id, org_id) not in store.memberships
    assert invitee.company_id != org_id


@pytest.mark.asyncio
async def test_tenant_isolation_admin_cannot_see_other_org_invites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    admin_a = _user(org_id=org_a, role=UserRole.ADMIN, email="admin-a@test")
    admin_b = _user(org_id=org_b, role=UserRole.ADMIN, email="admin-b@test")
    current: dict[str, User] = {"user": admin_a}

    invite_b = OrganizationInvite(
        id=uuid.uuid4(),
        organization_id=org_b,
        email="x@b.test",
        role="MEMBER",
        token_hash=hash_invite_token("secret-b"),
        expires_at=_now() + timedelta(days=3),
        is_accepted=False,
        created_at=_now(),
        invited_by_id=admin_b.id,
    )
    store.invites[invite_b.id] = invite_b

    service = InviteService()
    monkeypatch.setattr(invite_mod, "invite_service", service)
    monkeypatch.setattr(
        "app.api.endpoints.billing.invites.invite_service",
        service,
    )

    app = FastAPI()
    app.include_router(invites_router, prefix="/api/v1")

    async def _override_user() -> User:
        return current["user"]

    async def _override_db():
        yield FakeSession(store)

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/v1/organizations/invites")
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 0

        created = await client.post(
            "/api/v1/organizations/invites",
            json={"email": "new@a.test", "role": "MEMBER"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["organization_id"] == str(org_a)
        assert all(
            i.organization_id == org_a for i in store.invites.values() if i.email == "new@a.test"
        )

        revoked = await client.delete(f"/api/v1/organizations/invites/{invite_b.id}")
        assert revoked.status_code == 404
        assert invite_b.id in store.invites


def test_rbac_section_matrix() -> None:
    assert can_manage_billing(UserRole.OWNER) is True
    assert can_manage_billing(UserRole.ADMIN) is True
    assert can_manage_billing(UserRole.MEMBER) is False
    assert can_manage_billing(UserRole.OPERATOR) is False

    assert can_manage_flows(UserRole.OWNER) is True
    assert can_manage_flows(UserRole.ADMIN) is True
    assert can_manage_flows(UserRole.MEMBER) is True
    assert can_manage_flows(UserRole.OPERATOR) is False

    assert can_manage_crm(UserRole.OWNER) is True
    assert can_manage_crm(UserRole.ADMIN) is True
    assert can_manage_crm(UserRole.OPERATOR) is True
    assert can_manage_crm(UserRole.MEMBER) is False

    assert can_manage_settings(UserRole.OWNER) is True
    assert can_manage_settings(UserRole.ADMIN) is True
    assert can_manage_settings(UserRole.MEMBER) is False
    assert can_manage_settings(UserRole.OPERATOR) is False

    assert Permission.MANAGE_BILLING.value == "manage:billing"
    assert Permission.MANAGE_FLOWS.value == "manage:flows"
    assert Permission.MANAGE_CRM.value == "manage:crm"
    assert Permission.MANAGE_SETTINGS.value == "manage:settings"
