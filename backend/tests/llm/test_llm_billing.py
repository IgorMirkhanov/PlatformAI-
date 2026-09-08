"""Step 1.3 — LLM Gateway token billing via WalletService."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.billing.wallet_service import DeductResult, InsufficientFundsError
from app.services.llm.base import InsufficientCreditsForLLMError, LLMResponse
from app.services.llm.gateway import ResilientLLMGateway
from app.services.llm.pricing import LLM_TX_TYPE, calculate_cost, estimate_request_credits


class FakeProvider:
    """Minimal provider double (avoids ABC boilerplate)."""

    provider_id = "openai"
    model = "gpt-4o-mini"

    def __init__(self, response: LLMResponse | None = None) -> None:
        self.complete_calls = 0
        self._response = response or LLMResponse(
            content="ok",
            tool_calls=None,
            prompt_tokens=100,
            completion_tokens=42,
            model_name="gpt-4o-mini",
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        self.complete_calls += 1
        base = self._response
        return LLMResponse(
            content=base.content,
            tool_calls=base.tool_calls,
            prompt_tokens=base.prompt_tokens,
            completion_tokens=base.completion_tokens,
            model_name=base.model_name,
            raw=dict(base.raw or {}),
            billing_handled=base.billing_handled,
        )


def _wallet_mock(*, balance: int = 10_000) -> MagicMock:
    wallet = MagicMock()
    wallet.get_balance = AsyncMock(return_value=balance)
    wallet.get_or_create_wallet = AsyncMock()
    wallet.deduct_credits = AsyncMock(
        side_effect=lambda db, org_id, amount, tx_type, reference_id=None: DeductResult(
            organization_id=org_id,
            amount=amount,
            balance_before=balance,
            balance_after=balance - amount,
            transaction_id=uuid.uuid4(),
            idempotent_replay=False,
        )
    )
    return wallet


@pytest.mark.asyncio
async def test_complete_for_organization_deducts_exact_credits() -> None:
    org_id = uuid.uuid4()
    provider = FakeProvider(
        LLMResponse(
            content="billed",
            tool_calls=None,
            prompt_tokens=100,
            completion_tokens=42,
            model_name="gpt-4o-mini",
        )
    )
    expected = calculate_cost("gpt-4o-mini", 100, 42)
    assert expected > 0

    wallet = _wallet_mock(balance=10_000)
    gateway = ResilientLLMGateway([provider], wallet_service=wallet)  # type: ignore[list-item]
    db = MagicMock()

    result = await gateway.complete_for_organization(
        db,
        org_id,
        [{"role": "user", "content": "hello"}],
        max_tokens=100,
        reference_id="llm-req-1",
    )

    assert result.content == "billed"
    assert provider.complete_calls == 1
    wallet.deduct_credits.assert_awaited_once()
    call = wallet.deduct_credits.await_args
    assert call.args[1] == org_id
    assert call.args[2] == expected
    assert call.args[3] == LLM_TX_TYPE
    assert call.kwargs["reference_id"] == "llm-req-1"
    assert result.raw["billing"]["credits"] == expected
    assert result.raw["billing"]["reference_id"] == "llm-req-1"
    assert result.billing_handled is True
    assert result.raw["billing_handled"] is True


@pytest.mark.asyncio
async def test_dual_billing_skipped_when_already_handled() -> None:
    """Gateway must not charge again if upstream already settled billing."""
    org_id = uuid.uuid4()
    provider = FakeProvider(
        LLMResponse(
            content="pre-billed",
            tool_calls=None,
            prompt_tokens=100,
            completion_tokens=42,
            model_name="gpt-4o-mini",
            billing_handled=True,
        )
    )
    wallet = _wallet_mock(balance=10_000)
    gateway = ResilientLLMGateway([provider], wallet_service=wallet)  # type: ignore[list-item]

    result = await gateway.complete_for_organization(
        MagicMock(),
        org_id,
        [{"role": "user", "content": "hello"}],
        max_tokens=100,
        reference_id="already-billed",
    )

    assert result.content == "pre-billed"
    assert result.billing_handled is True
    wallet.deduct_credits.assert_not_awaited()
    assert provider.complete_calls == 1


@pytest.mark.asyncio
async def test_insufficient_credits_blocks_provider_call() -> None:
    org_id = uuid.uuid4()
    provider = FakeProvider()
    wallet = _wallet_mock(balance=0)
    gateway = ResilientLLMGateway([provider], wallet_service=wallet)  # type: ignore[list-item]
    db = MagicMock()

    messages = [{"role": "user", "content": "expensive request"}]
    estimated = estimate_request_credits("gpt-4o-mini", messages, 100)
    assert estimated > 0

    with pytest.raises(InsufficientCreditsForLLMError) as exc_info:
        await gateway.complete_for_organization(
            db,
            org_id,
            messages,
            max_tokens=100,
        )

    assert provider.complete_calls == 0
    wallet.deduct_credits.assert_not_awaited()
    assert exc_info.value.status_code == 402
    assert exc_info.value.balance == 0
    assert exc_info.value.required == estimated


@pytest.mark.asyncio
async def test_deduct_idempotent_same_reference_id() -> None:
    org_id = uuid.uuid4()
    response = LLMResponse(
        content="once",
        tool_calls=None,
        prompt_tokens=100,
        completion_tokens=42,
        model_name="gpt-4o-mini",
    )
    expected = calculate_cost("gpt-4o-mini", 100, 42)
    provider = FakeProvider(response)

    balances = {"value": 1_000}

    seen_refs: set[str] = set()

    async def deduct_side_effect(
        db: Any,
        organization_id: uuid.UUID,
        amount: int,
        tx_type: str,
        reference_id: str | None = None,
    ) -> DeductResult:
        # Simulate WalletService reference_id idempotency.
        ref = (reference_id or "").strip()
        if ref and ref in seen_refs:
            return DeductResult(
                organization_id=organization_id,
                amount=0,
                balance_before=balances["value"],
                balance_after=balances["value"],
                transaction_id=uuid.uuid4(),
                idempotent_replay=True,
            )
        if ref:
            seen_refs.add(ref)
        balances["value"] -= amount
        return DeductResult(
            organization_id=organization_id,
            amount=amount,
            balance_before=balances["value"] + amount,
            balance_after=balances["value"],
            transaction_id=uuid.uuid4(),
            idempotent_replay=False,
        )

    wallet = _wallet_mock(balance=1_000)
    wallet.deduct_credits = AsyncMock(side_effect=deduct_side_effect)
    gateway = ResilientLLMGateway([provider], wallet_service=wallet)  # type: ignore[list-item]
    db = MagicMock()
    ref = "idempotent-llm-ref"

    first = await gateway.complete_for_organization(
        db, org_id, [{"role": "user", "content": "a"}], max_tokens=100, reference_id=ref
    )
    second = await gateway.complete_for_organization(
        db, org_id, [{"role": "user", "content": "a"}], max_tokens=100, reference_id=ref
    )

    assert first.raw["billing"]["idempotent_replay"] is False
    assert second.raw["billing"]["idempotent_replay"] is True
    assert wallet.deduct_credits.await_count == 2
    assert balances["value"] == 1_000 - expected
    # Both calls billed the same computed amount; only first mutated balance.
    amounts = [c.args[2] for c in wallet.deduct_credits.await_args_list]
    assert amounts == [expected, expected]
    refs = [c.kwargs["reference_id"] for c in wallet.deduct_credits.await_args_list]
    assert refs == [ref, ref]


def test_calculate_cost_known_model() -> None:
    # 1000 prompt @ 5/1k + 1000 completion @ 20/1k = 5 + 20 = 25
    assert calculate_cost("gpt-4o-mini", 1000, 1000) == 25
    assert calculate_cost("gpt-4o-mini-2024-07-18", 1000, 1000) == 25
    assert calculate_cost("llama3", 5000, 5000) == 0


def test_calculate_cost_free_suffix_and_paid_on_free_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "openai/gpt-oss-20b")
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq", raising=False)
    monkeypatch.setattr(settings, "OPENAI_CHAT_MODEL", "openai/gpt-oss-20b", raising=False)

    assert calculate_cost("meta-llama/llama-3.2-3b-instruct:free", 1000, 1000) == 0
    assert calculate_cost("gpt-4o-mini", 1000, 1000) == 25
    assert calculate_cost(settings.resolved_chat_model, 1000, 1000) == 0


def test_effective_chat_model_rewrites_openai_aliases_on_groq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq", raising=False)
    monkeypatch.setattr(settings, "GROQ_CHAT_MODEL", "openai/gpt-oss-20b", raising=False)
    monkeypatch.setattr(settings, "OPENAI_CHAT_MODEL", "gpt-4o-mini", raising=False)

    assert settings.effective_chat_model("gpt-4o-mini") == "openai/gpt-oss-20b"
    assert settings.effective_chat_model(None) == "openai/gpt-oss-20b"
    assert settings.effective_chat_model("claude-4.5-haiku") == "claude-4.5-haiku"


def test_effective_chat_model_rewrites_openai_aliases_on_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini", raising=False)
    monkeypatch.setattr(settings, "GEMINI_CHAT_MODEL", "gemini-2.5-flash", raising=False)
    monkeypatch.setattr(settings, "OPENAI_CHAT_MODEL", "gpt-4o-mini", raising=False)

    assert settings.resolved_chat_model == "gemini-2.5-flash"
    assert settings.effective_chat_model("gpt-4o-mini") == "gemini-2.5-flash"
    assert settings.is_free_llm_route is True


@pytest.mark.asyncio
async def test_post_deduct_insufficient_maps_to_llm_error() -> None:
    """Race after preflight: deduct raises → standardized 402 error."""
    org_id = uuid.uuid4()
    provider = FakeProvider()
    wallet = _wallet_mock(balance=10_000)
    wallet.deduct_credits = AsyncMock(
        side_effect=InsufficientFundsError(
            "race",
            organization_id=org_id,
            balance=0,
            required=99,
        )
    )
    gateway = ResilientLLMGateway([provider], wallet_service=wallet)  # type: ignore[list-item]

    with pytest.raises(InsufficientCreditsForLLMError) as exc_info:
        await gateway.complete_for_organization(
            MagicMock(),
            org_id,
            [{"role": "user", "content": "x"}],
            max_tokens=50,
            reference_id="race-1",
        )

    assert provider.complete_calls == 1
    assert exc_info.value.status_code == 402
    assert exc_info.value.required == 99
