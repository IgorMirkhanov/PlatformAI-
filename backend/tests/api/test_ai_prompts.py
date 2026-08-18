"""Tests for POST /api/v1/ai/optimize-prompt."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.rbac import get_current_user
from app.services.prompt_optimization_service import PromptOptimizeResult
from main import app


@pytest.fixture
def org_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.company_id = uuid.uuid4()
    user.role = "ADMIN"
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
async def test_optimize_prompt_returns_enhanced_text(
    api_client: AsyncClient,
    org_user: MagicMock,
) -> None:
    mock_result = PromptOptimizeResult(
        optimized_prompt="# Role\nYou are MP.AI support agent.\n",
        model_name="gpt-4o-mini",
        prompt_tokens=42,
        completion_tokens=88,
    )

    with patch(
        "app.api.endpoints.ai_prompts.prompt_optimization_service.optimize_prompt_for_organization",
        new=AsyncMock(return_value=mock_result),
    ):
        response = await api_client.post(
            "/api/v1/ai/optimize-prompt",
            json={
                "prompt_text": "Ты бот поддержки",
                "bot_task": "Отвечать на вопросы клиентов",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "MP.AI support agent" in body["optimized_prompt"]
    assert body["model_name"] == "gpt-4o-mini"
    assert body["prompt_tokens"] == 42
    assert body["completion_tokens"] == 88


@pytest.mark.asyncio
async def test_optimize_prompt_rejects_empty_text(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/ai/optimize-prompt",
        json={"prompt_text": ""},
    )
    assert response.status_code == 422
