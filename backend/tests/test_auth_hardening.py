"""Auth hardening — soft-launch disabled in prod, OAuth stub gated."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core import rbac as rbac_mod
from app.core.config import settings


@pytest.mark.asyncio
async def test_soft_launch_blocked_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "ALLOW_SOFT_LAUNCH_AUTH", True, raising=False)

    db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await rbac_mod.get_current_user(
            db=db,
            x_user_id=str(uuid.uuid4()),
            x_company_id=None,
            authorization=None,
            user_id=None,
        )
    assert exc_info.value.status_code == 401
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_soft_launch_blocked_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "development", raising=False)
    monkeypatch.setattr(settings, "ALLOW_SOFT_LAUNCH_AUTH", False, raising=False)

    db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await rbac_mod.get_current_user(
            db=db,
            x_user_id=None,
            x_company_id=None,
            authorization=None,
            user_id=None,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_oauth_stub_disabled_by_default() -> None:
    from app.api.routers import auth as auth_router

    with pytest.raises(HTTPException) as exc_info:
        await auth_router.oauth_start("google")
    assert exc_info.value.status_code == 501


@pytest.mark.asyncio
async def test_oauth_callback_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routers import auth as auth_router
    from app.schemas.auth import OAuthStubCallbackRequest
    from starlette.requests import Request

    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "ALLOW_OAUTH_STUB", True, raising=False)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/auth/oauth/callback",
        "raw_path": b"/api/v1/auth/oauth/callback",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    request = Request(scope)
    payload = OAuthStubCallbackRequest(
        provider="google",
        provider_account_id="abc",
        email="x@example.com",
    )
    with pytest.raises(HTTPException) as exc_info:
        await auth_router.oauth_callback_stub(request, payload, db=MagicMock())
    assert exc_info.value.status_code == 501
