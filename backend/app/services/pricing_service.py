"""LLM provider pricing (USD per 1M tokens) + cost helpers."""

from __future__ import annotations

from typing import TypedDict


class ModelPrice(TypedDict):
    input: float
    output: float


# Prices are USD per 1,000,000 tokens (OpenAI list prices as of 2025).
LLM_PRICING: dict[str, ModelPrice] = {
    "gpt-4o": {"input": 5.00, "output": 15.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "llama3": {"input": 0.0, "output": 0.0},
}

# Fallback blended rate when model is unknown (USD / 1M tokens).
_DEFAULT_PRICE: ModelPrice = {"input": 1.00, "output": 3.00}

# Wallet ledger is KZT — convert USD cost before debiting Subscription.balance.
USD_TO_KZT = 450.0


def normalize_model_name(model_name: str | None) -> str:
    raw = (model_name or "").strip().lower()
    if not raw:
        return "gpt-4o-mini"
    # Strip date / version suffixes: "gpt-4o-2024-08-06" → "gpt-4o"
    for known in LLM_PRICING:
        if raw == known or raw.startswith(f"{known}-") or raw.startswith(f"{known}/"):
            return known
    return raw


def calculate_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """
    Return USD cost for a completion using per-1M input/output rates.
    """
    key = normalize_model_name(model_name)
    price = LLM_PRICING.get(key, _DEFAULT_PRICE)
    prompt = max(0, int(prompt_tokens))
    completion = max(0, int(completion_tokens))
    cost = (prompt / 1_000_000.0) * float(price["input"]) + (
        completion / 1_000_000.0
    ) * float(price["output"])
    return round(cost, 8)


def cost_usd_to_kzt(cost_usd: float, *, rate: float | None = None) -> float:
    fx = float(rate if rate is not None else USD_TO_KZT)
    return round(float(cost_usd) * fx, 4)


class PricingService:
    calculate_cost = staticmethod(calculate_cost)
    cost_usd_to_kzt = staticmethod(cost_usd_to_kzt)
    normalize_model_name = staticmethod(normalize_model_name)


pricing_service = PricingService()
