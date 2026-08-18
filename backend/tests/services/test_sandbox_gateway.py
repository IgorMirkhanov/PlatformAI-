"""Tests for org-billed LLM gateway routing in orchestrator and sandbox."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai_orchestrator import AIOrchestrator
from app.services.llm.base import LLMResponse


@pytest.mark.asyncio
async def test_orchestrator_uses_gateway_when_bot_and_db_present() -> None:
    org_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    db = MagicMock()
    gateway_response = LLMResponse(
        content="Gateway reply",
        tool_calls=None,
        prompt_tokens=12,
        completion_tokens=8,
        model_name="gpt-4o-mini",
        raw={"billing": {"credits": 3, "reference_id": "ref-1"}},
        billing_handled=True,
    )

    orchestrator = AIOrchestrator()
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]

    with (
        patch(
            "app.services.ai_orchestrator.llm_response_cache.get_cached_response",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai_orchestrator.llm_response_cache.get_semantic_cached_response",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai_orchestrator.llm_response_cache.set_cached_response",
            new=AsyncMock(),
        ),
        patch(
            "app.services.ai_orchestrator.llm_response_cache.register_semantic_turn",
            new=AsyncMock(),
        ),
        patch(
            "app.services.internal_llm_service.resolve_bot_organization_id",
            new=AsyncMock(return_value=org_id),
        ),
        patch(
            "app.services.internal_llm_service.complete_via_gateway",
            new=AsyncMock(return_value=gateway_response),
        ) as gateway_mock,
    ):
        result = await orchestrator._request_completion_with_usage(
            messages,
            model_name="gpt-4o-mini",
            temperature=0.4,
            bot_id=bot_id,
            db=db,
            source="sandbox",
        )

    assert result.text == "Gateway reply"
    assert result.billing_handled is True
    assert result.input_tokens == 12
    assert result.output_tokens == 8
    gateway_mock.assert_awaited_once()
    call_kwargs = gateway_mock.await_args.kwargs
    assert call_kwargs["source"] == "sandbox"
    assert call_kwargs["model_name"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_sandbox_ai_turn_calls_orchestrator_with_history() -> None:
    from app.services.sandbox_service import SandboxService

    bot_id = uuid.uuid4()
    db = MagicMock()
    bot = MagicMock()
    bot.llm_model_name = "gpt-4o-mini"
    bot.llm_temperature = 0.5
    bot.prompt_instructions = "Global bot instructions"

    flow = MagicMock()
    flow.graph_data = {
        "nodes": [{"id": "ai", "type": "ai_agent", "data": {"prompt_context": "You help"}}],
        "edges": [],
    }

    service = SandboxService()
    session = service.get_or_create_session(bot_id, "sess-1")
    session.history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]

    next_node = {
        "node_id": "ai",
        "node_type": "ai_agent",
        "requires_ai": True,
        "text": "",
        "buttons": [],
        "data": {"prompt_context": "You help", "model_name": "gpt-4o-mini"},
        "llm_model_name": "gpt-4o-mini",
        "llm_temperature": 0.5,
    }

    with (
        patch.object(service, "_load_bot", new=AsyncMock(return_value=bot)),
        patch.object(service, "_load_published_flow", new=AsyncMock(return_value=flow)),
        patch(
            "app.services.sandbox_service.FlowExecutor.find_next_node",
            return_value=next_node,
        ),
        patch(
            "app.services.sandbox_service.AIOrchestrator.generate_ai_response_with_trace",
            new=AsyncMock(return_value=("Sandbox AI reply", MagicMock())),
        ) as orchestrator_mock,
    ):
        response = await service.process_message(
            db,
            bot_id,
            "Need pricing info",
            session_id="sess-1",
        )

    assert "Sandbox AI reply" in response.message
    orchestrator_mock.assert_awaited_once()
    call_kwargs = orchestrator_mock.await_args.kwargs
    assert call_kwargs["history"] == session.history
    assert call_kwargs["channel"] == "sandbox"
    assert call_kwargs["model_name"] == "gpt-4o-mini"
    assert call_kwargs["global_prompt"] == "Global bot instructions"
