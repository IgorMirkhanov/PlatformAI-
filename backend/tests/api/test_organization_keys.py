"""Tests for organization LLM API key endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.rbac import get_current_user
from app.schemas.organization_api_keys import (
    OrganizationApiKeyListResponse,
    OrganizationApiKeyProviderStatus,
    OrganizationApiKeyUpsertResponse,
)
from app.services.ai_keys_service import AiKeysServiceError
from main import app


@pytest.fixture
def org_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.company_id = uuid.uuid4()
    user.role = "ADMIN"
    return user


@pytest.fixture
def operator_user(org_user: MagicMock) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.company_id = org_user.company_id
    user.role = "OPERATOR"
    return user


@pytest.fixture
async def api_client(org_user: MagicMock) -> AsyncIterator[AsyncClient]:
    async def _override_db() -> AsyncIterator[MagicMock]:
        db = MagicMock()
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: org_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_organization_api_keys_returns_masked_status(
    api_client: AsyncClient,
) -> None:
    now = datetime.now(timezone.utc)
    mock_response = OrganizationApiKeyListResponse(
        items=[
            OrganizationApiKeyProviderStatus(
                provider="openai",
                label="OpenAI",
                configured=True,
                is_active=True,
                masked_key="sk-...abcd",
                updated_at=now,
            ),
            OrganizationApiKeyProviderStatus(
                provider="anthropic",
                label="Anthropic",
                configured=False,
                is_active=False,
                masked_key=None,
                updated_at=None,
            ),
        ]
    )

    with patch(
        "app.api.endpoints.organization_keys.ai_keys_service.list_provider_status",
        new=AsyncMock(return_value=mock_response),
    ):
        response = await api_client.get("/api/v1/organizations/api-keys")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["provider"] == "openai"
    assert body["items"][0]["masked_key"] == "sk-...abcd"
    assert body["items"][1]["configured"] is False


@pytest.mark.asyncio
async def test_upsert_organization_api_key_saves_encrypted_key(
    api_client: AsyncClient,
) -> None:
    mock_response = OrganizationApiKeyUpsertResponse(
        provider="openai",
        configured=True,
        masked_key="sk-...wxyz",
        is_active=True,
    )

    with patch(
        "app.api.endpoints.organization_keys.ai_keys_service.upsert_key",
        new=AsyncMock(return_value=mock_response),
    ) as upsert_mock:
        response = await api_client.post(
            "/api/v1/organizations/api-keys",
            json={
                "provider": "openai",
                "api_key": "sk-test-secret-key-12345",
                "is_active": True,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "openai"
    assert body["configured"] is True
    assert body["masked_key"] == "sk-...wxyz"
    upsert_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_organization_api_key_returns_204(api_client: AsyncClient) -> None:
    with patch(
        "app.api.endpoints.organization_keys.ai_keys_service.delete_key",
        new=AsyncMock(return_value=None),
    ) as delete_mock:
        response = await api_client.delete("/api/v1/organizations/api-keys/openai")

    assert response.status_code == 204, response.text
    delete_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_organization_api_key_not_found(api_client: AsyncClient) -> None:
    with patch(
        "app.api.endpoints.organization_keys.ai_keys_service.delete_key",
        new=AsyncMock(side_effect=AiKeysServiceError("API key not found for this provider.", 404)),
    ):
        response = await api_client.delete("/api/v1/organizations/api-keys/openai")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_organization_api_keys_forbidden_for_operator(
    operator_user: MagicMock,
) -> None:
    async def _override_db() -> AsyncIterator[MagicMock]:
        db = MagicMock()
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: operator_user
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/organizations/api-keys")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
