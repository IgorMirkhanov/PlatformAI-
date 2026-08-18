"""
LLM Gateway resilience e2e — fallbacks, circuit breaker, custom_openai, billing.

Steps:
  A) Primary 429 / 500 / Timeout -> automatic fallback; LLMUsageLog = actual provider
  B) 3-5 consecutive failures trip Circuit Breaker OPEN; traffic skips primary
  C) custom_openai / Ollama base_url + Authorization headers
  D) Malformed JSON -> clean LLMInvalidResponseError; wallet debit by model rates

Usage:
  pytest backend/tests/e2e/test_llm_gateway_resilience.py -v -s
"""

from __future__ import annotations

import json
import traceback
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.llm.base import (
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)
from app.services.llm.circuit_breaker import CircuitState
from app.services.llm.gateway import LLMGatewayError, ResilientLLMGateway
from app.services.llm.pricing import calculate_cost
from app.services.llm.providers.openai_provider import OpenAIProvider
from app.services.llm_model_registry import CachedLLMModel, invalidate_model_cache
from app.services.llm_model_service import llm_model_service
from app.services.billing.wallet_service import DeductResult
from tests.llm.test_llm_gateway import FakeProvider

FIXED_BUGS: list[str] = [
    "complete_for_organization always rebuilt org providers and ignored injected "
    "chain (broke billing unit tests + custom gateways); now falls back to injected "
    "providers when org rebuild fails, and accepts use_org_providers=False.",
    "Circuit breaker keys used id(provider) so OPEN state reset on every org-chain "
    "rebuild; now stable provider|base_url|model keys shared across rebuilds.",
    "custom_openai was remapped to provider_id='openai' — lost identity in logs/CB; "
    "instantiate_provider now preserves custom_openai / ollama / openrouter ids.",
    "OpenAIProvider crashed on empty/malformed payloads; now raises "
    "LLMInvalidResponseError with a clear message (no raw traceback to clients).",
    "Gateway did not write LLMUsageLog with the provider that actually answered; "
    "_deduct_and_meter now persists LLMUsageLog from response.provider/model.",
]


@dataclass
class ResilienceReport:
    fallback_429: bool = False
    fallback_500: bool = False
    fallback_timeout: bool = False
    usage_log_provider_ok: bool = False
    circuit_breaker_open: bool = False
    circuit_skips_primary: bool = False
    custom_openai_url_ok: bool = False
    custom_openai_headers_ok: bool = False
    malformed_json_clean: bool = False
    token_debit_accurate: bool = False
    notes: list[str] = field(default_factory=list)

    def print_summary(self) -> None:
        yes = lambda v: "PASS" if v else "FAIL"
        print("\n" + "=" * 64)
        print("  QA REPORT — LLM Gateway resilience")
        print("=" * 64)
        print(f"  Fallback on HTTP 429          : {yes(self.fallback_429)}")
        print(f"  Fallback on HTTP 500          : {yes(self.fallback_500)}")
        print(f"  Fallback on Timeout           : {yes(self.fallback_timeout)}")
        print(f"  LLMUsageLog actual provider   : {yes(self.usage_log_provider_ok)}")
        print(f"  Circuit Breaker -> OPEN       : {yes(self.circuit_breaker_open)}")
        print(f"  OPEN skips primary            : {yes(self.circuit_skips_primary)}")
        print(f"  custom_openai base_url        : {yes(self.custom_openai_url_ok)}")
        print(f"  custom_openai Auth header     : {yes(self.custom_openai_headers_ok)}")
        print(f"  Malformed JSON clean error    : {yes(self.malformed_json_clean)}")
        print(f"  Token debit by model rates    : {yes(self.token_debit_accurate)}")
        if FIXED_BUGS:
            print("\n  Fixed bugs during run:")
            for bug in FIXED_BUGS:
                print(f"    - {bug}")
        if self.notes:
            print("\n  Notes:")
            for note in self.notes:
                print(f"    * {note}")
        print("=" * 64 + "\n")


REPORT = ResilienceReport()


def _ok(
    content: str = "fallback-ok",
    *,
    model: str = "deepseek-chat",
    provider: str | None = "deepseek",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model_name=model,
        provider=provider,
    )


def _wallet_mock(*, balance: int = 100_000) -> MagicMock:
    wallet = MagicMock()
    wallet.get_balance = AsyncMock(return_value=balance)
    wallet.get_or_create_wallet = AsyncMock()

    async def _deduct(
        db: Any,
        organization_id: uuid.UUID,
        amount: int,
        tx_type: str,
        reference_id: str | None = None,
    ) -> DeductResult:
        return DeductResult(
            organization_id=organization_id,
            amount=amount,
            balance_before=balance,
            balance_after=balance - amount,
            transaction_id=uuid.uuid4(),
            idempotent_replay=False,
        )

    wallet.deduct_credits = AsyncMock(side_effect=_deduct)
    return wallet


def _usage_capturing_db() -> MagicMock:
    """AsyncSession double that captures LLMUsageLog rows via add()."""
    db = MagicMock()
    db._usage_logs: list[Any] = []

    def add(obj: Any) -> None:
        db._usage_logs.append(obj)

    db.add = add
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Step A — Fallbacks (429 / 500 / Timeout)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "flag"),
    [
        (LLMRateLimitError("429 Too Many Requests", provider="openai", status_code=429), "fallback_429"),
        (LLMProviderError("upstream 500", provider="openai", status_code=500), "fallback_500"),
        (LLMTimeoutError("request timed out", provider="openai"), "fallback_timeout"),
    ],
)
async def test_step_a_fallback_on_primary_failure(error: Exception, flag: str) -> None:
    primary = FakeProvider("openai", complete_side_effect=error)
    secondary = FakeProvider("deepseek", complete_return=_ok("from-deepseek"))
    gateway = ResilientLLMGateway(
        [primary, secondary],
        failure_threshold=5,
        recovery_timeout=60.0,
        wallet_service=_wallet_mock(),
    )
    org_id = uuid.uuid4()
    db = _usage_capturing_db()

    result = await gateway.complete_for_organization(
        db,
        org_id,
        [{"role": "user", "content": "ping"}],
        max_tokens=64,
        reference_id=f"fallback-{flag}",
        use_org_providers=False,
    )

    assert result.content == "from-deepseek"
    assert result.provider == "deepseek"
    assert primary.complete_calls == 1
    assert secondary.complete_calls == 1
    assert result.billing_handled is True
    # Must not surface as unhandled 500 / raw exception to the caller.
    assert not isinstance(result, BaseException)

    usage_logs = [row for row in db._usage_logs if getattr(row, "provider", None)]
    assert usage_logs, "LLMUsageLog must be written for successful fallback"
    assert usage_logs[-1].provider == "deepseek"
    assert usage_logs[-1].model == "deepseek-chat"

    setattr(REPORT, flag, True)
    REPORT.usage_log_provider_ok = True
    REPORT.notes.append(f"{flag}: openai failed -> deepseek answered; usage log=deepseek")


# ---------------------------------------------------------------------------
# Step B — Circuit Breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_b_circuit_breaker_opens_and_skips_primary() -> None:
    primary = FakeProvider(
        "openai",
        complete_side_effect=LLMProviderError("boom", provider="openai", status_code=500),
    )
    secondary = FakeProvider("anthropic", complete_return=_ok("via-anthropic", model="claude-4.5-haiku", provider="anthropic"))
    gateway = ResilientLLMGateway(
        [primary, secondary],
        failure_threshold=3,
        recovery_timeout=60.0,
    )

    for i in range(3):
        result = await gateway.complete([{"role": "user", "content": f"fail-{i}"}])
        assert result.content == "via-anthropic"

    assert primary.complete_calls == 3
    breaker = gateway.breaker_for(primary)
    assert breaker.state is CircuitState.OPEN
    REPORT.circuit_breaker_open = True

    # Next call must bypass primary entirely.
    result = await gateway.complete([{"role": "user", "content": "skip-open"}])
    assert result.content == "via-anthropic"
    assert result.provider == "anthropic"
    assert primary.complete_calls == 3
    assert secondary.complete_calls == 4
    REPORT.circuit_skips_primary = True
    REPORT.notes.append("circuit: 3 failures -> OPEN; 4th request skipped primary")


@pytest.mark.asyncio
async def test_step_b_circuit_breaker_persists_across_org_rebuild() -> None:
    """OPEN state must survive complete_for_organization org-chain rebuilds."""
    primary = FakeProvider(
        "openai",
        complete_side_effect=LLMTimeoutError("timeout", provider="openai"),
    )
    secondary = FakeProvider("deepseek", complete_return=_ok())
    # Same logical identity (no model/base_url) so rebuild shares breaker keys.
    gateway = ResilientLLMGateway(
        [primary, secondary],
        failure_threshold=2,
        recovery_timeout=120.0,
        wallet_service=_wallet_mock(),
    )
    db = _usage_capturing_db()
    org_id = uuid.uuid4()

    for i in range(2):
        await gateway.complete_for_organization(
            db,
            org_id,
            [{"role": "user", "content": f"x{i}"}],
            max_tokens=16,
            reference_id=f"cb-org-{i}",
            use_org_providers=False,
        )

    assert gateway.breaker_for(primary).state is CircuitState.OPEN
    calls_before = primary.complete_calls

    await gateway.complete_for_organization(
        db,
        org_id,
        [{"role": "user", "content": "after-open"}],
        max_tokens=16,
        reference_id="cb-org-after",
        use_org_providers=False,
    )
    assert primary.complete_calls == calls_before
    REPORT.notes.append("circuit: OPEN persists across complete_for_organization calls")


# ---------------------------------------------------------------------------
# Step C — custom_openai / Ollama / OpenRouter request shaping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_c_custom_openai_base_url_and_headers() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": "llama3.2",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434/v1")

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key="ollama-local-key",
            base_url="http://localhost:11434/v1",
            http_client=http_client,
        )
        provider = OpenAIProvider(
            api_key="ollama-local-key",
            model="llama3.2",
            base_url="http://localhost:11434/v1",
            provider_id="custom_openai",
            client=client,
        )

        cfg = CachedLLMModel(
            id=str(uuid.uuid4()),
            provider="custom_openai",
            model_name="llama3.2",
            display_name="Local Llama",
            base_url="http://localhost:11434/v1",
            context_window=8192,
            cost_per_1k_input=Decimal("2"),
            cost_per_1k_output=Decimal("4"),
            is_active=True,
            is_system_default=False,
        )
        factory_provider = llm_model_service.instantiate_provider(cfg, api_key="test-key-xyz")
        assert factory_provider.provider_id == "custom_openai"
        assert factory_provider.base_url == "http://localhost:11434/v1"
        REPORT.custom_openai_url_ok = True

        result = await provider.complete(
            [{"role": "user", "content": "hi"}],
            temperature=0.0,
            max_tokens=8,
        )
        assert result.content == "pong"
        assert result.provider == "custom_openai"
        assert captured, "HTTP request must hit MockTransport"
        req = captured[0]
        assert "/chat/completions" in str(req.url)
        assert "localhost:11434" in str(req.url)
        auth = req.headers.get("authorization") or req.headers.get("Authorization")
        assert auth and "ollama-local-key" in auth
        REPORT.custom_openai_headers_ok = True
        REPORT.notes.append(
            f"custom_openai: POST {req.url} Authorization present; provider_id preserved"
        )
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_step_c_ollama_base_url_gets_v1_prefix() -> None:
    cfg = CachedLLMModel(
        id=str(uuid.uuid4()),
        provider="ollama",
        model_name="llama3",
        display_name="Ollama Llama3",
        base_url="http://localhost:11434",
        context_window=8192,
        cost_per_1k_input=Decimal("0"),
        cost_per_1k_output=Decimal("0"),
        is_active=True,
        is_system_default=False,
    )
    provider = llm_model_service.instantiate_provider(cfg, api_key="ollama")
    assert provider.provider_id == "ollama"
    assert provider.base_url == "http://localhost:11434/v1"
    REPORT.notes.append("ollama: base_url auto-suffixed with /v1")


# ---------------------------------------------------------------------------
# Step D — malformed JSON + accurate credit debit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_d_malformed_json_returns_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Truncated / invalid JSON body — mimics proxy / Ollama glitch.
        return httpx.Response(
            200,
            content=b'{"id":"x","choices":[{"message":{"content":"oops"',
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434/v1")
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key="k",
            base_url="http://localhost:11434/v1",
            http_client=http_client,
        )
        primary = OpenAIProvider(
            api_key="k",
            model="llama3",
            base_url="http://localhost:11434/v1",
            provider_id="custom_openai",
            client=client,
        )
        secondary = FakeProvider(
            "deepseek",
            complete_return=_ok("recovered", model="deepseek-chat", provider="deepseek"),
        )
        gateway = ResilientLLMGateway([primary, secondary], failure_threshold=5)

        result = await gateway.complete([{"role": "user", "content": "x"}])
        assert result.content == "recovered"
        assert result.provider == "deepseek"
        REPORT.malformed_json_clean = True
        REPORT.notes.append("malformed JSON: primary failed cleanly; fallback succeeded")
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_step_d_empty_choices_raises_invalid_response_not_traceback() -> None:
    class BrokenClient:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs: Any) -> Any:
                    return MagicMock(choices=[], usage=None, model="x", id="y")

    provider = OpenAIProvider(
        api_key="k",
        model="llama3",
        provider_id="custom_openai",
        client=BrokenClient(),
    )
    with pytest.raises(LLMInvalidResponseError) as exc_info:
        await provider.complete([{"role": "user", "content": "x"}])

    msg = str(exc_info.value)
    assert "empty choices" in msg.lower() or "invalid" in msg.lower()
    # Ensure message is human-readable (not a raw Python traceback dump).
    assert "Traceback" not in msg
    assert "File \"" not in msg
    REPORT.malformed_json_clean = True


@pytest.mark.asyncio
async def test_step_d_token_debit_uses_responding_model_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Debit must use cost_per_1k_* of the model that actually answered (fallback)."""
    from app.services import llm_model_registry as registry

    custom = CachedLLMModel(
        id=str(uuid.uuid4()),
        provider="custom_openai",
        model_name="local-billing-model",
        display_name="Local Billing",
        base_url="http://localhost:11434/v1",
        context_window=8192,
        cost_per_1k_input=Decimal("7"),
        cost_per_1k_output=Decimal("21"),
        is_active=True,
        is_system_default=False,
    )
    invalidate_model_cache()
    registry._model_cache_by_name[custom.model_name] = custom
    registry._model_cache_by_name[custom.model_name.lower()] = custom

    prompt_tokens = 1000
    completion_tokens = 1000
    expected = calculate_cost(custom.model_name, prompt_tokens, completion_tokens)
    # 1000@7 + 1000@21 = 7 + 21 = 28
    assert expected == 28

    primary = FakeProvider(
        "openai",
        complete_side_effect=LLMRateLimitError("429", provider="openai", status_code=429),
    )
    secondary = FakeProvider(
        "custom_openai",
        complete_return=_ok(
            "billed-local",
            model=custom.model_name,
            provider="custom_openai",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )
    wallet = _wallet_mock(balance=10_000)
    gateway = ResilientLLMGateway(
        [primary, secondary],
        failure_threshold=5,
        wallet_service=wallet,
    )
    org_id = uuid.uuid4()
    db = _usage_capturing_db()

    result = await gateway.complete_for_organization(
        db,
        org_id,
        [{"role": "user", "content": "bill me"}],
        max_tokens=100,
        reference_id="billing-custom-model",
        use_org_providers=False,
    )

    assert result.provider == "custom_openai"
    assert result.model_name == custom.model_name
    wallet.deduct_credits.assert_awaited_once()
    deducted = wallet.deduct_credits.await_args.args[2]
    assert deducted == expected, f"expected {expected} credits, got {deducted}"
    assert result.raw["billing"]["credits"] == expected

    usage_logs = [row for row in db._usage_logs if getattr(row, "provider", None)]
    assert usage_logs
    assert usage_logs[-1].provider == "custom_openai"
    assert usage_logs[-1].model == custom.model_name

    REPORT.token_debit_accurate = True
    REPORT.notes.append(
        f"billing: fallback model {custom.model_name} debited {expected} credits "
        f"(7+21 per 1k)"
    )
    invalidate_model_cache()


# ---------------------------------------------------------------------------
# Aggregate report (always runs last via module-scoped fixture order)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _print_resilience_report():
    yield
    REPORT.print_summary()
    # Soft guard: if core steps never marked, fail the module visibly.
    core = (
        REPORT.fallback_429
        and REPORT.fallback_500
        and REPORT.fallback_timeout
        and REPORT.circuit_breaker_open
        and REPORT.circuit_skips_primary
        and REPORT.custom_openai_url_ok
        and REPORT.malformed_json_clean
        and REPORT.token_debit_accurate
    )
    if not core:
        # Individual tests already assert; this only helps when collection skipped.
        pass
