"""Step 1.2 — Resilient LLM Gateway: fallback chain + circuit breaker."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.llm.base import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)
from app.services.llm.circuit_breaker import CircuitBreaker, CircuitState
from app.services.llm.gateway import LLMGatewayError, ResilientLLMGateway


class FakeProvider(BaseLLMProvider):
    """Deterministic test double with injectable complete behavior."""

    def __init__(
        self,
        provider_id: str,
        *,
        complete_side_effect: Any = None,
        complete_return: LLMResponse | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.api_key = api_key
        self.model = model
        self.complete_calls = 0
        self._complete = AsyncMock(side_effect=complete_side_effect, return_value=complete_return)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        self.complete_calls += 1
        return await self._complete(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )


def _ok(content: str = "fallback-ok", model: str = "fake-model") -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=None,
        prompt_tokens=3,
        completion_tokens=5,
        model_name=model,
    )


# ---------------------------------------------------------------------------
# CircuitBreaker unit behaviour
# ---------------------------------------------------------------------------


def test_circuit_breaker_opens_after_threshold() -> None:
    clock = {"t": 0.0}
    cb = CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=60.0,
        time_fn=lambda: clock["t"],
    )
    assert cb.state is CircuitState.CLOSED
    for _ in range(2):
        assert cb.allow_request()
        cb.record_failure()
        assert cb.state is CircuitState.CLOSED
    assert cb.allow_request()
    cb.record_failure()
    assert cb.state is CircuitState.OPEN
    assert cb.allow_request() is False


def test_circuit_breaker_half_open_then_close_on_success() -> None:
    clock = {"t": 0.0}
    cb = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout=10.0,
        time_fn=lambda: clock["t"],
    )
    cb.record_failure()
    cb.record_failure()
    assert cb.state is CircuitState.OPEN
    assert cb.allow_request() is False

    clock["t"] = 10.0
    assert cb.state is CircuitState.HALF_OPEN
    assert cb.allow_request() is True
    # Second concurrent probe while first in-flight is rejected.
    assert cb.allow_request() is False

    cb.record_success()
    assert cb.state is CircuitState.CLOSED
    assert cb.failure_count == 0


def test_circuit_breaker_half_open_failure_reopens() -> None:
    clock = {"t": 0.0}
    cb = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout=5.0,
        time_fn=lambda: clock["t"],
    )
    cb.record_failure()
    assert cb.state is CircuitState.OPEN
    clock["t"] = 5.0
    assert cb.allow_request() is True
    cb.record_failure()
    assert cb.state is CircuitState.OPEN
    assert cb.allow_request() is False


# ---------------------------------------------------------------------------
# Gateway fallback / CB / total failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_fallback_on_rate_limit() -> None:
    messages = [{"role": "user", "content": "keep context"}]
    primary = FakeProvider(
        "openai",
        complete_side_effect=LLMRateLimitError(
            "429 Too Many Requests",
            provider="openai",
            status_code=429,
        ),
    )
    fallback = FakeProvider("anthropic", complete_return=_ok("from-fallback"))

    gateway = ResilientLLMGateway(
        [primary, fallback],
        failure_threshold=5,
        recovery_timeout=60.0,
    )
    result = await gateway.complete(messages, temperature=0.1, max_tokens=50)

    assert result.content == "from-fallback"
    assert primary.complete_calls == 1
    assert fallback.complete_calls == 1
    # Context (messages + kwargs) forwarded to fallback unchanged.
    call_kwargs = fallback._complete.await_args
    assert call_kwargs.args[0] == messages
    assert call_kwargs.kwargs["temperature"] == 0.1
    assert call_kwargs.kwargs["max_tokens"] == 50


@pytest.mark.asyncio
async def test_gateway_retries_configured_fallback_before_other_vendors() -> None:
    """FALLBACK_LLM_PROVIDER answers first, even when listed last in the chain."""
    primary = FakeProvider(
        "openrouter",
        complete_side_effect=LLMRateLimitError("429", provider="openrouter", status_code=429),
        api_key="sk-or-test",
        model="openai/gpt-oss-20b:free",
    )
    paid = FakeProvider(
        "openai",
        complete_return=_ok("from-paid-model"),
        api_key="sk-test",
        model="gpt-4o",
    )
    groq = FakeProvider(
        "groq",
        complete_return=_ok("from-groq", model="llama-3.1-8b-instant"),
        api_key="gsk-test",
        model="llama-3.1-8b-instant",
    )

    gateway = ResilientLLMGateway([primary, paid, groq])
    result = await gateway.complete([{"role": "user", "content": "x"}])

    assert result.content == "from-groq"
    assert groq.complete_calls == 1
    assert paid.complete_calls == 0


@pytest.mark.asyncio
async def test_gateway_drops_foreign_model_hint_on_fallback() -> None:
    """Groq must be asked for its own model, not the primary's OpenRouter slug."""
    primary = FakeProvider(
        "openrouter",
        complete_side_effect=LLMTimeoutError("timeout", provider="openrouter"),
        api_key="sk-or-test",
        model="openai/gpt-oss-20b:free",
    )
    groq = FakeProvider(
        "groq",
        complete_return=_ok("from-groq", model="llama-3.1-8b-instant"),
        api_key="gsk-test",
        model="llama-3.1-8b-instant",
    )

    gateway = ResilientLLMGateway([primary, groq])
    result = await gateway.complete(
        [{"role": "user", "content": "x"}],
        model="openai/gpt-oss-20b:free",
    )

    assert result.content == "from-groq"
    assert primary._complete.await_args.kwargs["model"] == "openai/gpt-oss-20b:free"
    assert "model" not in groq._complete.await_args.kwargs


@pytest.mark.asyncio
async def test_gateway_circuit_breaker_skips_open_primary() -> None:
    """After N consecutive primary failures, later calls skip primary immediately."""
    primary = FakeProvider(
        "openai",
        complete_side_effect=LLMTimeoutError("timeout", provider="openai"),
    )
    fallback = FakeProvider("openai-fallback", complete_return=_ok("via-fallback"))

    gateway = ResilientLLMGateway(
        [primary, fallback],
        failure_threshold=3,
        recovery_timeout=60.0,
    )

    # Trip the primary breaker (3 failures); each call also succeeds via fallback.
    for _ in range(3):
        result = await gateway.complete([{"role": "user", "content": "x"}])
        assert result.content == "via-fallback"

    assert primary.complete_calls == 3
    assert gateway.breaker_for(primary).state is CircuitState.OPEN

    # Next request must not touch the open primary.
    result = await gateway.complete([{"role": "user", "content": "skip-primary"}])
    assert result.content == "via-fallback"
    assert primary.complete_calls == 3
    assert fallback.complete_calls == 4


@pytest.mark.asyncio
async def test_gateway_all_providers_fail_raises_gateway_error() -> None:
    primary = FakeProvider(
        "openai",
        complete_side_effect=LLMProviderError("primary down", provider="openai", status_code=500),
    )
    secondary = FakeProvider(
        "anthropic",
        complete_side_effect=LLMRateLimitError("fallback 429", provider="anthropic", status_code=429),
    )
    gateway = ResilientLLMGateway([primary, secondary], failure_threshold=10)

    with pytest.raises(LLMGatewayError) as exc_info:
        await gateway.complete([{"role": "user", "content": "x"}])

    err = exc_info.value
    assert len(err.failures) == 2
    assert err.attempted == ["openai", "anthropic"]
    assert primary.complete_calls == 1
    assert secondary.complete_calls == 1


@pytest.mark.asyncio
async def test_gateway_all_circuit_open_raises_gateway_error() -> None:
    clock = {"t": 0.0}
    primary_cb = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout=60.0,
        name="primary",
        time_fn=lambda: clock["t"],
    )
    fallback_cb = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout=60.0,
        name="fallback",
        time_fn=lambda: clock["t"],
    )
    primary_cb.record_failure()
    fallback_cb.record_failure()
    assert primary_cb.state is CircuitState.OPEN
    assert fallback_cb.state is CircuitState.OPEN

    primary = FakeProvider("openai", complete_return=_ok("should-not-run"))
    fallback = FakeProvider("anthropic", complete_return=_ok("should-not-run"))
    gateway = ResilientLLMGateway(
        [primary, fallback],
        circuit_breakers={
            ResilientLLMGateway._provider_key(primary): primary_cb,
            ResilientLLMGateway._provider_key(fallback): fallback_cb,
        },
    )

    with pytest.raises(LLMGatewayError):
        await gateway.complete([{"role": "user", "content": "x"}])

    assert primary.complete_calls == 0
    assert fallback.complete_calls == 0


@pytest.mark.asyncio
async def test_gateway_auth_error_does_not_trip_circuit_breaker() -> None:
    primary = FakeProvider(
        "openai",
        complete_side_effect=LLMAuthenticationError(
            "401 invalid api key",
            provider="openai",
            status_code=401,
        ),
    )
    fallback = FakeProvider("anthropic", complete_return=_ok("via-fallback"))

    gateway = ResilientLLMGateway(
        [primary, fallback],
        failure_threshold=2,
        recovery_timeout=60.0,
    )

    result = await gateway.complete([{"role": "user", "content": "x"}])

    assert result.content == "via-fallback"
    assert primary.complete_calls == 1
    assert fallback.complete_calls == 1
    assert gateway.breaker_for(primary).failure_count == 0
    assert gateway.breaker_for(primary).state is CircuitState.CLOSED
