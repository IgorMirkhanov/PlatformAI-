"""Unit tests — Sentry telemetry scrubbing + LLM circuit-breaker outage alerts."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from app.core.telemetry import REDACTED, before_send_scrub_sensitive_data
from app.services.llm.base import LLMResponse, LLMTimeoutError
from app.services.llm.circuit_breaker import CircuitState
from app.services.llm.gateway import ResilientLLMGateway, _sentry_circuit_open_alert
from tests.llm.test_llm_billing import FakeProvider

OPENAI_KEY = "sk-proj-" + ("a" * 40)
ANTHROPIC_KEY = "sk-ant-" + ("b" * 40)


def test_before_send_scrubs_api_keys() -> None:
    event = {
        "message": f"openai={OPENAI_KEY} anthropic={ANTHROPIC_KEY}",
        "extra": {
            "openai_key": OPENAI_KEY,
            "anthropic_key": ANTHROPIC_KEY,
            "note": "safe text",
        },
        "request": {
            "headers": {
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
                "X-Debug": f"leak {ANTHROPIC_KEY}",
            }
        },
    }

    scrubbed = before_send_scrub_sensitive_data(event, hint={})
    assert scrubbed is not None

    blob = str(scrubbed)
    assert OPENAI_KEY not in blob
    assert ANTHROPIC_KEY not in blob
    assert "sk-proj-" not in blob
    assert "sk-ant-" not in blob
    assert REDACTED in scrubbed["message"]
    assert scrubbed["extra"]["openai_key"] == REDACTED
    assert scrubbed["extra"]["anthropic_key"] == REDACTED
    assert scrubbed["extra"]["note"] == "safe text"
    assert scrubbed["request"]["headers"]["Authorization"] == REDACTED
    assert REDACTED in scrubbed["request"]["headers"]["X-Debug"]
    assert scrubbed["request"]["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_circuit_breaker_sentry_event() -> None:
    """Trip CB OPEN via gateway failure → capture_message with llm_provider_outage tag."""

    class FailProvider(FakeProvider):
        provider_id = "openai"
        model = "gpt-4o-mini"

        async def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise LLMTimeoutError("provider timeout", provider="openai")

    class OkProvider(FakeProvider):
        provider_id = "anthropic"
        model = "claude-3-5"

        def __init__(self) -> None:
            super().__init__(
                LLMResponse(
                    content="fallback-ok",
                    tool_calls=None,
                    prompt_tokens=1,
                    completion_tokens=1,
                    model_name="claude-3-5",
                )
            )

    scope = MagicMock()
    scope_cm = MagicMock()
    scope_cm.__enter__.return_value = scope
    scope_cm.__exit__.return_value = False

    fake_sentry = types.ModuleType("sentry_sdk")
    fake_sentry.push_scope = MagicMock(return_value=scope_cm)
    fake_sentry.capture_message = MagicMock()
    fake_sentry.add_breadcrumb = MagicMock()

    with patch.dict(sys.modules, {"sentry_sdk": fake_sentry}):
        gateway = ResilientLLMGateway(
            [FailProvider(), OkProvider()],
            failure_threshold=1,
            recovery_timeout=60.0,
        )
        response = await gateway.complete([{"role": "user", "content": "ping"}])

    assert response.content == "fallback-ok"
    assert gateway.breaker_for(FailProvider()).state is CircuitState.OPEN

    fake_sentry.capture_message.assert_called()
    message, kwargs = _capture_call_args(fake_sentry.capture_message)
    assert "LLM Provider Down" in message
    assert "openai" in message
    assert "Circuit Breaker OPEN" in message
    assert kwargs.get("level") == "error"

    tag_calls = {args[0]: args[1] for args, _ in scope.set_tag.call_args_list}
    assert tag_calls.get("alert_type") == "llm_provider_outage"
    assert tag_calls.get("provider") == "openai"
    assert tag_calls.get("model") == "gpt-4o-mini"
    scope.set_extra.assert_any_call("last_error", "provider timeout")


def test_circuit_breaker_sentry_event_direct_helper() -> None:
    """Direct unit check of the outage helper (no async gateway path)."""
    scope = MagicMock()
    scope_cm = MagicMock()
    scope_cm.__enter__.return_value = scope
    scope_cm.__exit__.return_value = False

    fake_sentry = types.ModuleType("sentry_sdk")
    fake_sentry.push_scope = MagicMock(return_value=scope_cm)
    fake_sentry.capture_message = MagicMock()

    with patch.dict(sys.modules, {"sentry_sdk": fake_sentry}):
        _sentry_circuit_open_alert(
            provider_id="deepseek",
            model_name="deepseek-chat",
            error=RuntimeError("connection reset"),
        )

    fake_sentry.capture_message.assert_called_once()
    message, kwargs = _capture_call_args(fake_sentry.capture_message)
    assert "deepseek" in message
    assert "deepseek-chat" in message
    assert kwargs.get("level") == "error"
    tag_calls = {args[0]: args[1] for args, _ in scope.set_tag.call_args_list}
    assert tag_calls["alert_type"] == "llm_provider_outage"
    assert tag_calls["provider"] == "deepseek"
    assert tag_calls["model"] == "deepseek-chat"


def _capture_call_args(mock_capture: MagicMock) -> tuple[str, dict]:
    args, kwargs = mock_capture.call_args
    message = args[0] if args else kwargs.get("message", "")
    return str(message), dict(kwargs)
