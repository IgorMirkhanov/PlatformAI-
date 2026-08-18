"""E2E integration — Telegram webhook → FlowExecutor → LLMGateway → billing → outbound."""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.security import encrypt_credential, hash_bot_token
from app.models.core_models import Bot, BotFlow, Client, Company, PlatformType, UserRole
from app.models.users import User
from app.services.llm.base import LLMResponse
from app.services.llm.gateway import ResilientLLMGateway
from app.services.llm.pricing import calculate_cost
from app.services.telegram_service import telegram_service
from tests.llm.test_llm_billing import FakeProvider, _wallet_mock


def _telegram_update(*, chat_id: int = 12345, text: str = "Привет, какой статус заказа?") -> dict[str, Any]:
    return {
        "update_id": 9001,
        "message": {
            "message_id": 77,
            "from": {
                "id": chat_id,
                "is_bot": False,
                "first_name": "Aigerim",
                "username": "aigerim_test",
            },
            "chat": {
                "id": chat_id,
                "first_name": "Aigerim",
                "username": "aigerim_test",
                "type": "private",
            },
            "date": 1_700_000_000,
            "text": text,
        },
    }


def _llm_flow_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "id": "trigger",
                "type": "trigger",
                "data": {"trigger_type": "message_received"},
            },
            {
                "id": "ai",
                "type": "ai_agent",
                "data": {
                    "prompt_context": "You are MP.AI support. Answer briefly in Russian.",
                    "knowledge_base_id": "",
                    "prompt_modifier": "",
                    "model_name": "gpt-4o-mini",
                    "temperature": 0.3,
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "ai"},
        ],
    }


@pytest.fixture
def e2e_bot_stack() -> dict[str, Any]:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    token = "1234567890:AAE2E-test-bot-token"

    user = User(
        id=user_id,
        email=f"e2e-{org_id.hex[:10]}@mp.ai.test",
        hashed_password="!",
        company_name="E2E Org",
        full_name="E2E Owner",
        company_id=org_id,
        role=UserRole.OWNER,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )
    company = Company(
        id=org_id,
        name="E2E Org",
        owner_user_id=user_id,
        timezone="Asia/Almaty",
    )
    bot = Bot(
        id=bot_id,
        user_id=user_id,
        organization_id=org_id,
        name="E2E Telegram Bot",
        platform_type=PlatformType.TELEGRAM,
        is_active=True,
        credentials={
            "token_hash": hash_bot_token(token),
            "telegram_bot_token": encrypt_credential(token),
        },
        prompt_instructions="Global bot instructions for E2E.",
        llm_model_name="gpt-4o-mini",
        llm_temperature=0.4,
        user=user,
    )
    flow = BotFlow(
        id=flow_id,
        bot_id=bot_id,
        title="E2E LLM Flow",
        graph_data=_llm_flow_graph(),
        is_published=True,
        updated_at=datetime.now(timezone.utc),
    )
    return {
        "org_id": org_id,
        "user": user,
        "company": company,
        "bot": bot,
        "flow": flow,
        "token": token,
        "token_hash": hash_bot_token(token),
    }


@pytest.mark.asyncio
async def test_e2e_telegram_webhook_flow_engine_llm_gateway_billing(e2e_bot_stack: dict[str, Any]) -> None:
    """
    Full lifecycle:
    Telegram webhook → process_inbound_message → FlowExecutor (ai_agent)
    → AIOrchestrator → LLMGateway (mock provider) → wallet debit → sendMessage.
    """
    stack = e2e_bot_stack
    bot: Bot = stack["bot"]
    flow: BotFlow = stack["flow"]
    org_id: uuid.UUID = stack["org_id"]
    token_hash: str = stack["token_hash"]

    gateway_response = LLMResponse(
        content="Ваш заказ в обработке. Ожидайте уведомление в течение 24 часов.",
        tool_calls=None,
        prompt_tokens=120,
        completion_tokens=36,
        model_name="gpt-4o-mini",
    )
    provider = FakeProvider(gateway_response)
    wallet = _wallet_mock(balance=50_000)
    gateway = ResilientLLMGateway([provider], wallet_service=wallet)  # type: ignore[list-item]
    expected_credits = calculate_cost("gpt-4o-mini", 120, 36)

    stored_client: Client | None = None
    outbound_messages: list[dict[str, Any]] = []

    async def _get_or_create_client(
        db: Any,
        bot_id: uuid.UUID,
        external_id: str,
        username: str,
        first_name: str,
    ) -> Client:
        nonlocal stored_client
        if stored_client is None:
            stored_client = Client(
                id=uuid.uuid4(),
                bot_id=bot_id,
                external_id=external_id,
                username=username,
                first_name=first_name,
                current_step_id="",
                is_paused_by_operator=False,
            )
            stored_client.bot = bot
        return stored_client

    async def _capture_send_message(**kwargs: Any) -> None:
        outbound_messages.append(kwargs)

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.get = AsyncMock(return_value=stack["company"])

    mock_quota_module = MagicMock()
    mock_quota_module.quota_service = MagicMock(assert_token_quota=AsyncMock())
    mock_quota_module.QuotaExceeded = type("QuotaExceeded", (Exception,), {})

    mock_guardrails = MagicMock()
    mock_guardrails.check_text = AsyncMock(
        return_value=MagicMock(allowed=True, redacted_text=_telegram_update()["message"]["text"])
    )

    patches = [
        patch.dict(sys.modules, {"app.services.quota_service": mock_quota_module}),
        patch(
            "app.services.ai_guardrails.ai_guardrails_service",
            mock_guardrails,
        ),
        patch(
            "app.services.telegram_service.telegram_service.get_bot_by_token_hash",
            new=AsyncMock(return_value=bot),
        ),
        patch(
            "app.services.telegram_service.telegram_service._client_on_ai_node",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.telegram_service.telegram_service._client_paused_by_operator",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.telegram_service.telegram_service.send_message",
            new=AsyncMock(side_effect=_capture_send_message),
        ),
        patch(
            "app.services.telegram_service.telegram_service.answer_callback_query",
            new=AsyncMock(),
        ),
        patch("app.services.webhook_service._get_bot", new=AsyncMock(return_value=bot)),
        patch(
            "app.services.webhook_service._get_or_create_client",
            new=AsyncMock(side_effect=_get_or_create_client),
        ),
        patch(
            "app.services.webhook_service._get_latest_published_flow",
            new=AsyncMock(return_value=flow),
        ),
        patch("app.services.webhook_service.broadcast_chat_message", new=AsyncMock()),
        patch("app.services.webhook_service._enqueue_lead_capture"),
        patch(
            "app.services.ai_orchestrator.AIOrchestrator._assert_sufficient_balance",
            new=AsyncMock(),
        ),
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
            "app.services.ai_orchestrator.AIOrchestrator._fetch_rag_context_detailed",
            new=AsyncMock(return_value=([], "")),
        ),
        patch(
            "app.services.ai_orchestrator.AIOrchestrator._fetch_chat_history",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.internal_llm_service.resolve_bot_organization_id",
            new=AsyncMock(return_value=org_id),
        ),
        patch(
            "app.services.llm.factory.build_gateway_providers_for_organization",
            new=AsyncMock(return_value=[provider]),
        ),
        patch("app.services.llm.factory.get_llm_gateway", return_value=gateway),
        patch("app.services.llm.gateway.record_llm_usage_event", new=AsyncMock()),
        patch("app.services.ai_orchestrator.settings.OPENAI_API_KEY", ""),
        patch("app.services.ai_orchestrator.settings.LLM_PROVIDER", "openai"),
    ]

    with ExitStack() as patch_stack:
        for item in patches:
            patch_stack.enter_context(item)
        result = await telegram_service.process_queued_webhook(
            db=db,
            bot_token_hash=token_hash,
            update=_telegram_update(),
        )

    assert result["status"] == "processed"
    assert result.get("bot_silent") is not True
    assert provider.complete_calls == 1
    assert wallet.deduct_credits.await_count == 1

    deduct_call = wallet.deduct_credits.await_args
    assert deduct_call.args[1] == org_id
    assert deduct_call.args[2] == expected_credits

    assert len(outbound_messages) == 1
    outbound = outbound_messages[0]
    assert outbound["chat_id"] == "12345"
    assert "заказ в обработке" in outbound["text"].lower()
    assert outbound["bot_token"] == stack["token"]

    assert stored_client is not None
    assert stored_client.current_step_id == "ai"

    assert db.add.call_count >= 2
