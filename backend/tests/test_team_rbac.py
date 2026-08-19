"""Team tenancy / RBAC hardening tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.core_models import UserRole
from app.schemas.team_schemas import (
    SwitchCompanyRequest,
    TeamInviteRequest,
    UpdateTeamMemberRoleRequest,
)
from app.services.team_service import TeamService, _hash_invite_token


def _user(**overrides):
    base = {
        "id": uuid.uuid4(),
        "email": "owner@mp.ai",
        "full_name": "Owner",
        "company_name": "Acme",
        "company_id": uuid.uuid4(),
        "role": UserRole.OWNER,
        "timezone": "Asia/Almaty",
        "created_at": datetime.now(UTC),
        "is_superadmin": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_revoke_member_deletes_membership_not_user() -> None:
    service = TeamService()
    company_id = uuid.uuid4()
    actor = _user(company_id=company_id, role=UserRole.OWNER)
    member = _user(company_id=company_id, role=UserRole.OPERATOR, email="op@mp.ai")
    membership = SimpleNamespace(role=UserRole.OPERATOR, company_id=company_id, user_id=member.id)

    db = AsyncMock()
    service._get_company_membership = AsyncMock(return_value=(member, membership))  # type: ignore[method-assign]
    service._count_owners = AsyncMock(return_value=1)  # type: ignore[method-assign]
    service._rebind_active_company = AsyncMock()  # type: ignore[method-assign]

    await service.revoke_member(db, current_user=actor, member_id=member.id)

    db.delete.assert_awaited_once_with(membership)
    service._rebind_active_company.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_member_role_updates_membership_row() -> None:
    service = TeamService()
    company_id = uuid.uuid4()
    actor = _user(company_id=company_id, role=UserRole.OWNER)
    member = _user(company_id=company_id, role=UserRole.OPERATOR, email="op@mp.ai")
    membership = SimpleNamespace(role=UserRole.OPERATOR, company_id=company_id, user_id=member.id)

    db = AsyncMock()
    service._get_company_membership = AsyncMock(return_value=(member, membership))  # type: ignore[method-assign]
    service._count_owners = AsyncMock(return_value=1)  # type: ignore[method-assign]

    result = await service.update_member_role(
        db,
        current_user=actor,
        member_id=member.id,
        payload=UpdateTeamMemberRoleRequest(role=UserRole.PROMPT_ENGINEER),
    )

    assert membership.role == UserRole.PROMPT_ENGINEER
    assert member.role == UserRole.PROMPT_ENGINEER
    assert result.role == UserRole.PROMPT_ENGINEER


@pytest.mark.asyncio
async def test_admin_cannot_promote_to_admin() -> None:
    service = TeamService()
    company_id = uuid.uuid4()
    actor = _user(company_id=company_id, role=UserRole.ADMIN)
    member = _user(company_id=company_id, role=UserRole.OPERATOR, email="op@mp.ai")
    membership = SimpleNamespace(role=UserRole.OPERATOR, company_id=company_id, user_id=member.id)

    db = AsyncMock()
    service._get_company_membership = AsyncMock(return_value=(member, membership))  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="cannot promote"):
        await service.update_member_role(
            db,
            current_user=actor,
            member_id=member.id,
            payload=UpdateTeamMemberRoleRequest(role=UserRole.ADMIN),
        )


@pytest.mark.asyncio
async def test_admin_cannot_invite_admin() -> None:
    service = TeamService()
    actor = _user(role=UserRole.ADMIN)
    db = AsyncMock()
    service._ensure_seat_available = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="only invite"):
        await service.invite_member(
            db,
            current_user=actor,
            payload=TeamInviteRequest(email="new@mp.ai", role=UserRole.ADMIN),
        )


@pytest.mark.asyncio
async def test_invite_stores_hashed_token() -> None:
    service = TeamService()
    actor = _user(role=UserRole.OWNER)
    db = AsyncMock()
    service._ensure_seat_available = AsyncMock()  # type: ignore[method-assign]

    existing_user = MagicMock()
    existing_user.scalar_one_or_none.return_value = None
    pending = MagicMock()
    pending.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[existing_user, pending])

    async def _flush() -> None:
        invitation = db.add.call_args.args[0]
        invitation.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=_flush)

    response = await service.invite_member(
        db,
        current_user=actor,
        payload=TeamInviteRequest(email="new@mp.ai", role=UserRole.OPERATOR),
    )

    assert response.token
    assert len(response.token) >= 32
    from app.models.core_models import TeamInvitation

    added = next(
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], TeamInvitation)
    )
    assert added.token == _hash_invite_token(response.token)
    assert added.token != response.token


@pytest.mark.asyncio
async def test_apply_workspace_context_persist_updates_user() -> None:
    service = TeamService()
    company_id = uuid.uuid4()
    user = _user(company_id=uuid.uuid4(), role=UserRole.OWNER)
    membership = SimpleNamespace(role=UserRole.ADMIN)
    company = SimpleNamespace(id=company_id, name="Other Co")

    result_proxy = MagicMock()
    result_proxy.first.return_value = (membership, company)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)

    await service.apply_workspace_context(db, user, company_id, persist=True)
    assert user.company_id == company_id
    assert user.role == UserRole.ADMIN
    assert user.company_name == "Other Co"


@pytest.mark.asyncio
async def test_switch_company_returns_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TeamService()
    company_id = uuid.uuid4()
    user = _user(company_id=uuid.uuid4(), role=UserRole.OWNER)
    membership = SimpleNamespace(role=UserRole.ADMIN)
    company = SimpleNamespace(
        id=company_id,
        name="Other Co",
        timezone="UTC",
    )

    result_proxy = MagicMock()
    result_proxy.first.return_value = (membership, company)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)

    monkeypatch.setattr(
        "app.core.auth.mint_user_token",
        lambda _user: "minted.jwt.token",
    )

    response = await service.switch_company(
        db,
        current_user=user,
        payload=SwitchCompanyRequest(company_id=company_id),
    )
    assert response.access_token == "minted.jwt.token"
    assert response.company_id == company_id
    assert user.company_id == company_id


def test_invite_token_hash_is_sha256() -> None:
    raw = "abc123"
    assert _hash_invite_token(raw) == hashlib.sha256(raw.encode("utf-8")).hexdigest()
