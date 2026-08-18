"""TenantMiddleware / deps — block client spoofing of X-Tenant-Id."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from app.core import tenant as tenant_mod
from app.core.deps import resolve_tenant_organization_id
from app.core.tenant import (
    TenantContext,
    TenantMiddleware,
    allow_tenant_header_override,
    caller_is_superadmin_from_jwt,
    has_internal_service_key,
)


def _request(
    *,
    headers: dict[str, str] | None = None,
    path: str = "/api/v1/bots",
) -> Request:
    header_list = []
    for key, value in (headers or {}).items():
        header_list.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": header_list,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clear_internal_key(monkeypatch):
    monkeypatch.setattr(tenant_mod.settings, "INTERNAL_SERVICE_API_KEY", None, raising=False)


def test_regular_client_header_override_denied(monkeypatch):
    monkeypatch.setattr(tenant_mod.settings, "INTERNAL_SERVICE_API_KEY", "secret-key")
    req = _request(headers={"x-tenant-id": str(uuid.uuid4())})
    assert allow_tenant_header_override(req, claims={}) is False
    assert has_internal_service_key(req) is False


def test_internal_api_key_allows_header_override(monkeypatch):
    monkeypatch.setattr(tenant_mod.settings, "INTERNAL_SERVICE_API_KEY", "secret-key")
    req = _request(
        headers={
            "x-internal-api-key": "secret-key",
            "x-organization-id": str(uuid.uuid4()),
        }
    )
    assert has_internal_service_key(req) is True
    assert allow_tenant_header_override(req, claims={}) is True


def test_superadmin_jwt_allows_header_override():
    assert caller_is_superadmin_from_jwt({"is_superuser": True}) is True
    req = _request(headers={"x-tenant-id": str(uuid.uuid4())})
    assert allow_tenant_header_override(req, claims={"is_superuser": True}) is True


@pytest.mark.asyncio
async def test_middleware_ignores_spoofed_tenant_header_for_jwt_user(monkeypatch):
    victim_org = uuid.uuid4()
    user_org = uuid.uuid4()
    user_id = uuid.uuid4()

    def fake_decode(_token: str) -> dict:
        return {
            "sub": str(user_id),
            "company_id": str(user_org),
            "is_superuser": False,
        }

    monkeypatch.setattr("app.core.security.decode_access_token", fake_decode)
    monkeypatch.setattr(tenant_mod.settings, "INTERNAL_SERVICE_API_KEY", "svc-secret")

    captured: dict = {}

    async def call_next(request: Request):
        captured["tenant"] = request.state.tenant
        response = MagicMock()
        response.headers = {}
        return response

    mw = TenantMiddleware(app=MagicMock())
    req = _request(
        headers={
            "authorization": "Bearer user-token",
            "x-tenant-id": str(victim_org),
            "x-organization-id": str(victim_org),
        }
    )
    await mw.dispatch(req, call_next)

    tenant: TenantContext = captured["tenant"]
    assert tenant.organization_id == user_org
    assert tenant.source == "jwt"
    assert tenant.header_override_allowed is False


@pytest.mark.asyncio
async def test_middleware_accepts_header_with_internal_key(monkeypatch):
    target_org = uuid.uuid4()
    monkeypatch.setattr(tenant_mod.settings, "INTERNAL_SERVICE_API_KEY", "svc-secret")

    captured: dict = {}

    async def call_next(request: Request):
        captured["tenant"] = request.state.tenant
        response = MagicMock()
        response.headers = {}
        return response

    mw = TenantMiddleware(app=MagicMock())
    req = _request(
        headers={
            "x-internal-api-key": "svc-secret",
            "x-tenant-id": str(target_org),
        }
    )
    await mw.dispatch(req, call_next)

    tenant: TenantContext = captured["tenant"]
    assert tenant.organization_id == target_org
    assert tenant.source == "internal"
    assert tenant.header_override_allowed is True


@pytest.mark.asyncio
async def test_middleware_superadmin_may_override_via_header(monkeypatch):
    target_org = uuid.uuid4()
    jwt_org = uuid.uuid4()

    def fake_decode(_token: str) -> dict:
        return {
            "sub": str(uuid.uuid4()),
            "company_id": str(jwt_org),
            "is_superuser": True,
        }

    monkeypatch.setattr("app.core.security.decode_access_token", fake_decode)

    captured: dict = {}

    async def call_next(request: Request):
        captured["tenant"] = request.state.tenant
        response = MagicMock()
        response.headers = {}
        return response

    mw = TenantMiddleware(app=MagicMock())
    req = _request(
        headers={
            "authorization": "Bearer admin-token",
            "x-organization-id": str(target_org),
        }
    )
    await mw.dispatch(req, call_next)

    tenant: TenantContext = captured["tenant"]
    assert tenant.organization_id == target_org
    assert tenant.source == "superadmin_header"


@pytest.mark.asyncio
async def test_resolve_tenant_binds_regular_user_to_company_id():
    user_org = uuid.uuid4()
    spoof_org = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), company_id=user_org, is_superadmin=False)

    req = _request()
    req.state.tenant = TenantContext(
        organization_id=spoof_org,
        source="header",
        header_override_allowed=False,
    )

    resolved = await resolve_tenant_organization_id(req, db=MagicMock(), current_user=user)
    assert resolved == user_org
    assert req.state.tenant.organization_id == user_org
    assert req.state.tenant.source == "jwt"


@pytest.mark.asyncio
async def test_resolve_tenant_superadmin_keeps_trusted_override():
    admin_home = uuid.uuid4()
    target = uuid.uuid4()
    admin = SimpleNamespace(id=uuid.uuid4(), company_id=admin_home, is_superadmin=True)

    req = _request()
    req.state.tenant = TenantContext(
        organization_id=target,
        source="superadmin_header",
        header_override_allowed=True,
    )

    resolved = await resolve_tenant_organization_id(req, db=MagicMock(), current_user=admin)
    assert resolved == target
