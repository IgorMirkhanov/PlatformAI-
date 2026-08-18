"""Model catalog, pricing, and provider routing for the LLM gateway."""

from __future__ import annotations

import pytest

from app.services.llm.gateway import ResilientLLMGateway
from app.services.llm.pricing import (
    LLM_CREDIT_PRICING,
    MODEL_PROVIDER_MAP,
    calculate_cost,
    normalize_model_name,
    resolve_provider_for_model,
    supported_models,
)
from app.services.llm.base import LLMProviderError, LLMResponse


REQUIRED_MODELS = (
    # OpenAI
    "gpt-4.1",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5",
    "gpt-4o",
    "gpt-4o-mini",
    "o4-mini",
    "o3",
    "o3-mini",
    # Anthropic
    "claude-4.7-opus",
    "claude-4.6-opus",
    "claude-4.6-sonnet",
    "claude-4.5-sonnet",
    "claude-4.5-haiku",
    "claude-4.1-opus",
    # Gemini
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    # DeepSeek
    "deepseek-chat",
    "deepseek-reasoner",
    # GLM & Qwen
    "glm-5.1",
    "glm-5",
    "glm-5-turbo",
    "qwen-3.7-plus",
    "qwen-3.7-max",
)

EXPECTED_ROUTING = {
    "gpt-5.4-mini": "openai",
    "gpt-4o": "openai",
    "o3-mini": "openai",
    "claude-4.6-sonnet": "anthropic",
    "claude-4.5-haiku": "anthropic",
    "gemini-2.5-flash": "gemini",
    "deepseek-reasoner": "deepseek",
    "glm-5-turbo": "glm",
    "qwen-3.7-max": "qwen",
}


def test_required_models_are_in_pricing_registry() -> None:
    missing = [name for name in REQUIRED_MODELS if name not in LLM_CREDIT_PRICING]
    assert not missing, f"Missing pricing entries: {missing}"
    for name in REQUIRED_MODELS:
        assert name in MODEL_PROVIDER_MAP
        assert name in supported_models()


def test_normalize_prefers_longest_model_key() -> None:
    assert normalize_model_name("gpt-5.4-mini-2026-01") == "gpt-5.4-mini"
    assert normalize_model_name("gpt-5.4") == "gpt-5.4"
    assert normalize_model_name("GPT-4o-mini") == "gpt-4o-mini"
    assert normalize_model_name("claude-4.6-sonnet-latest") == "claude-4.6-sonnet"


@pytest.mark.parametrize("model,provider", list(EXPECTED_ROUTING.items()))
def test_resolve_provider_for_model(model: str, provider: str) -> None:
    assert resolve_provider_for_model(model) == provider


def test_calculate_cost_uses_registry_rates() -> None:
    # gpt-4o-mini: 5/1k prompt + 20/1k completion → 1000+1000 tokens = 5+20 = 25
    assert calculate_cost("gpt-4o-mini", 1000, 1000) == 25
    assert calculate_cost("llama3", 5000, 5000) == 0
    # New catalog entry must bill > 0
    assert calculate_cost("deepseek-chat", 1000, 1000) > 0
    assert calculate_cost("claude-4.7-opus", 100, 100) > 0


@pytest.mark.asyncio
async def test_gateway_routes_model_to_preferred_provider() -> None:
    """Preferred vendor is tried first when ``model=`` is set."""

    class TrackingProvider:
        provider_id = "openai"
        complete_calls = 0

        async def complete(self, *args, **kwargs):
            self.complete_calls += 1
            raise LLMProviderError("openai down", provider="openai")

    class PreferredProvider:
        provider_id = "anthropic"
        complete_calls = 0

        async def complete(self, *args, **kwargs):
            self.complete_calls += 1
            return LLMResponse(
                content="from-anthropic",
                tool_calls=None,
                prompt_tokens=3,
                completion_tokens=5,
                model_name=str(kwargs.get("model") or "claude-4.5-sonnet"),
            )

    openai = TrackingProvider()
    anthropic = PreferredProvider()
    gateway = ResilientLLMGateway([openai, anthropic])  # type: ignore[list-item]

    result = await gateway.complete(
        [{"role": "user", "content": "hi"}],
        model="claude-4.5-sonnet",
    )

    assert result.content == "from-anthropic"
    assert anthropic.complete_calls == 1
    # Preferred provider succeeded first — openai never called.
    assert openai.complete_calls == 0
