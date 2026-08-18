"""API tests for dynamic LLM model registry."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_superadmin
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.schemas.llm_models import LLMModelListResponse, LLMModelRead, LLMModelTestConnectionResponse
from main import app


@pytest.fixture
def org_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.company_id = uuid.uuid4()
    user.role = "ADMIN"
    user.is_superadmin = False
    return user


@pytest.fixture
def superadmin() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superadmin = True
    return user


@pytest.fixture
async def user_client(org_user: MagicMock) -> AsyncIterator[AsyncClient]:
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


@pytest.fixture
async def admin_client(superadmin: MagicMock) -> AsyncIterator[AsyncClient]:
    async def _override_db() -> AsyncIterator[MagicMock]:
        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_superadmin] = lambda: superadmin
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _sample_model() -> LLMModelRead:
    now = datetime.now(timezone.utc)
    return LLMModelRead(
        id=uuid.uuid4(),
        provider="custom_openai",
        model_name="llama3.1-8b",
        display_name="Llama 3.1 8B (Local)",
        base_url="http://localhost:11434/v1",
        context_window=8192,
        cost_per_1k_input=Decimal("0"),
        cost_per_1k_output=Decimal("0"),
        is_active=True,
        is_system_default=False,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_list_llm_models_returns_catalog(user_client: AsyncClient) -> None:
    sample = _sample_model()
    mock_response = LLMModelListResponse(items=[sample], total=1)
    with patch(
        "app.api.endpoints.llm_models.llm_model_service.list_models",
        new=AsyncMock(return_value=mock_response),
    ):
        response = await user_client.get("/api/v1/llm-models")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["model_name"] == "llama3.1-8b"


@pytest.mark.asyncio
async def test_admin_create_llm_model(superadmin: MagicMock, admin_client: AsyncClient) -> None:
    created = _sample_model()
    with patch(
        "app.api.endpoints.admin.llm_models.llm_model_service.create_model",
        new=AsyncMock(return_value=created),
    ):
        response = await admin_client.post(
            "/api/v1/admin/llm-models",
            json={
                "provider": "custom_openai",
                "model_name": "llama3.1-8b",
                "display_name": "Llama 3.1 8B (Local)",
                "base_url": "http://localhost:11434/v1",
                "context_window": 8192,
                "cost_per_1k_input": "0",
                "cost_per_1k_output": "0",
                "is_active": True,
                "is_system_default": False,
            },
        )
    assert response.status_code == 201
    assert response.json()["provider"] == "custom_openai"


@pytest.mark.asyncio
async def test_admin_deactivate_llm_model(admin_client: AsyncClient) -> None:
    model_id = uuid.uuid4()
    deactivated = _sample_model()
    deactivated.id = model_id
    deactivated.is_active = False
    with patch(
        "app.api.endpoints.admin.llm_models.llm_model_service.deactivate_model",
        new=AsyncMock(return_value=deactivated),
    ):
        response = await admin_client.delete(f"/api/v1/admin/llm-models/{model_id}")
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_test_connection_endpoint(user_client: AsyncClient) -> None:
    mock_result = LLMModelTestConnectionResponse(
        ok=True,
        latency_ms=42.5,
        model="llama3.1-8b",
        provider="custom_openai",
        message="Connection successful.",
        sample_reply="pong",
    )
    with patch(
        "app.api.endpoints.llm_models.llm_model_service.test_connection",
        new=AsyncMock(return_value=mock_result),
    ):
        response = await user_client.post(
            "/api/v1/llm-models/test-connection",
            json={
                "provider": "custom_openai",
                "model_name": "llama3.1-8b",
                "base_url": "http://localhost:11434/v1",
            },
        )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["sample_reply"] == "pong"
