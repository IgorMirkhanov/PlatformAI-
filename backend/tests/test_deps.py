"""Tests — bot workspace access deps (joinedload + membership checks)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import joinedload

from app.api import deps as deps_mod
from app.api.deps import _bot_accessible_in_workspace, get_bot_for_workspace
from app.models.core_models import Bot, PlatformType, UserRole
from app.models.users import User


def _user(
    *,
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    is_superadmin: bool = False,
    is_support: bool = False,
) -> User:
    uid = user_id or uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid}@example.com",
        hashed_password="!",
        company_name="Acme",
        full_name="Test",
        company_id=company_id or uid,
        role=UserRole.OWNER,
        is_superadmin=is_superadmin,
        is_support=is_support,
    )


def _bot(
    *,
    owner: User,
    organization_id: uuid.UUID | None = None,
) -> Bot:
    return Bot(
        id=uuid.uuid4(),
        user_id=owner.id,
        organization_id=organization_id if organization_id is not None else owner.company_id,
        name="Agent",
        platform_type=PlatformType.WHATSAPP,
        user=owner,
    )


class _Scalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)


class _Result:
    def __init__(self, *, scalars: list[Any] | None = None, unique_value: Any = None) -> None:
        self._scalars = scalars or []
        self._unique_value = unique_value

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalars)

    def unique(self) -> "_Result":
        return self

    def scalar_one_or_none(self) -> Any:
        return self._unique_value


@pytest.mark.asyncio
async def test_superadmin_always_accessible() -> None:
    owner = _user()
    admin = _user(is_superadmin=True)
    bot = _bot(owner=owner)
    db = AsyncMock()

    assert await _bot_accessible_in_workspace(db, user=admin, bot=bot) is True
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_owner_always_accessible() -> None:
    owner = _user()
    bot = _bot(owner=owner)
    db = AsyncMock()

    assert await _bot_accessible_in_workspace(db, user=owner, bot=bot) is True
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_workspace_member_same_org_single_membership_query() -> None:
    workspace_id = uuid.uuid4()
    owner = _user(company_id=workspace_id)
    member = _user(company_id=workspace_id)
    bot = _bot(owner=owner, organization_id=workspace_id)

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=_Result(scalars=[member.id, owner.id]),
    )

    assert await _bot_accessible_in_workspace(db, user=member, bot=bot) is True
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_outsider_denied() -> None:
    workspace_id = uuid.uuid4()
    other_workspace = uuid.uuid4()
    owner = _user(company_id=workspace_id)
    outsider = _user(company_id=other_workspace)
    bot = _bot(owner=owner, organization_id=workspace_id)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result(scalars=[]))

    assert await _bot_accessible_in_workspace(db, user=outsider, bot=bot) is False


@pytest.mark.asyncio
async def test_get_bot_for_workspace_uses_joinedload(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _user()
    bot = _bot(owner=owner)
    caller = _user(user_id=owner.id, company_id=owner.company_id)

    captured: dict[str, Any] = {}

    class _FakeResult:
        def unique(self) -> "_FakeResult":
            return self

        def scalar_one_or_none(self) -> Bot:
            return bot

    async def fake_execute(stmt: Any) -> _FakeResult:
        captured["stmt"] = stmt
        return _FakeResult()

    db = MagicMock()
    db.execute = AsyncMock(side_effect=fake_execute)

    monkeypatch.setattr(
        deps_mod,
        "require_workspace_member",
        AsyncMock(return_value=caller),
    )

    loaded = await get_bot_for_workspace(bot.id, db, caller)  # type: ignore[arg-type]
    assert loaded is bot

    stmt = captured["stmt"]
    option_specs = list(stmt._with_options)  # noqa: SLF001
    assert option_specs, "expected joinedload options on bot select"
    # joinedload paths should include Bot.user and Bot.organization
    joined_paths = []
    for opt in option_specs:
        path = getattr(opt, "path", None)
        if path is not None:
            joined_paths.append(str(path))
        else:
            joined_paths.append(repr(opt))
    blob = " ".join(joined_paths).lower()
    assert "user" in blob
    assert "organization" in blob


@pytest.mark.asyncio
async def test_get_bot_for_workspace_not_found() -> None:
    class _Empty:
        def unique(self) -> "_Empty":
            return self

        def scalar_one_or_none(self) -> None:
            return None

    db = MagicMock()
    db.execute = AsyncMock(return_value=_Empty())
    caller = _user()

    with pytest.raises(HTTPException) as exc_info:
        await get_bot_for_workspace(uuid.uuid4(), db, caller)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 404


def test_joinedload_helper_importable() -> None:
    """Smoke: strategy used by get_bot_for_workspace is the SQLAlchemy joinedload."""
    opt = joinedload(Bot.user)
    assert opt is not None
