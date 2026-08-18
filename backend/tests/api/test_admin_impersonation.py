"""Admin support search + impersonation access control tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.rbac import get_current_user
from app.schemas.admin import ImpersonationResponse
from main import app


@pytest.fixture
def regular_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.company_id = uuid.uuid4()
    user.role = "OWNER"
    user.is_superadmin = False
    user.is_support = False
    user._is_impersonating = False
    return user


@pytest.fixture
def support_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superadmin = False
    user.is_support = True
    user._is_impersonating = False
    return user


@pytest.fixture
def superadmin() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superadmin = True
    user.is_support = False
    user.hashed_password = "bcrypt:dummy"
    user._is_impersonating = False
    return user


def _client_for(user: MagicMock) -> AsyncIterator[AsyncClient]:
    async def _override_db() -> AsyncIterator[MagicMock]:
        db = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return ASGITransport(app=app)


@pytest.fixture
async def regular_client(regular_user: MagicMock) -> AsyncIterator[AsyncClient]:
    transport = _client_for(regular_user)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def support_client(support_user: MagicMock) -> AsyncIterator[AsyncClient]:
    transport = _client_for(support_user)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def superadmin_client(superadmin: MagicMock) -> AsyncIterator[AsyncClient]:
    transport = _client_for(superadmin)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_regular_user_forbidden_on_admin_search(regular_client: AsyncClient) -> None:
    response = await regular_client.get("/api/v1/admin/users/search", params={"query": "test"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_support_user_can_search(support_client: AsyncClient) -> None:
    response = await support_client.get("/api/v1/admin/users/search", params={"query": "client"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "client"
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_regular_user_forbidden_on_impersonate(regular_client: AsyncClient) -> None:
    response = await regular_client.post(
        "/api/v1/admin/impersonate",
        json={"user_email": "client@example.com", "password": "secret"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_support_forbidden_on_impersonate(support_client: AsyncClient) -> None:
    response = await support_client.post(
        "/api/v1/admin/impersonate",
        json={"user_email": "client@example.com", "password": "secret"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_impersonate_returns_token(superadmin_client: AsyncClient) -> None:
    now = datetime.now(timezone.utc)
    admin_id = uuid.uuid4()
    target_id = uuid.uuid4()
    org_id = uuid.uuid4()

    mock_response = ImpersonationResponse(
        access_token="jwt-token",
        organization_id=org_id,
        organization_name="Acme",
        impersonated_user_id=target_id,
        impersonated_user_email="client@example.com",
        impersonated_by=admin_id,
        expires_at=now,
    )

    target = MagicMock()
    target.id = target_id
    target.email = "client@example.com"
    target.is_superadmin = False
    target.is_support = False
    target.is_active = True

    result = MagicMock()
    result.scalar_one_or_none.return_value = target

    async def _override_db() -> AsyncIterator[MagicMock]:
        db = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=result)
        yield db

    app.dependency_overrides[get_db] = _override_db

    with patch(
        "app.api.endpoints.admin.impersonate.build_impersonation_response",
        new=AsyncMock(return_value=mock_response),
    ), patch("app.api.endpoints.admin.impersonate.assert_admin_reauth"):
        response = await superadmin_client.post(
            "/api/v1/admin/impersonate",
            json={"user_email": "client@example.com", "password": "secret"},
        )

    assert response.status_code == 200
    assert response.json()["access_token"] == "jwt-token"
