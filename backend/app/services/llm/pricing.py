"""LLM token → credit pricing and model → provider routing."""

from __future__ import annotations

from typing import Any, Final, TypedDict

from app.core.config import settings


class CreditModelPrice(TypedDict):
    """Credits charged per 1,000 tokens (prompt / completion)."""

    prompt_per_1k: int
    completion_per_1k: int


# ---------------------------------------------------------------------------
# Credit tariff table (integer billing units per 1k tokens)
# ---------------------------------------------------------------------------

LLM_CREDIT_PRICING: dict[str, CreditModelPrice] = {
    # OpenAI — GPT-5 family
    "gpt-5.5": {"prompt_per_1k": 200, "completion_per_1k": 800},
    "gpt-5.4": {"prompt_per_1k": 160, "completion_per_1k": 640},
    "gpt-5.4-mini": {"prompt_per_1k": 40, "completion_per_1k": 160},
    "gpt-5.4-nano": {"prompt_per_1k": 10, "completion_per_1k": 40},
    "gpt-5": {"prompt_per_1k": 120, "completion_per_1k": 480},
    # OpenAI — GPT-4.x / 4o
    "gpt-4.1": {"prompt_per_1k": 80, "completion_per_1k": 320},
    "gpt-4o": {"prompt_per_1k": 50, "completion_per_1k": 150},
    "gpt-4o-mini": {"prompt_per_1k": 5, "completion_per_1k": 20},
    "gpt-4-turbo": {"prompt_per_1k": 100, "completion_per_1k": 300},
    "gpt-3.5-turbo": {"prompt_per_1k": 10, "completion_per_1k": 30},
    # OpenAI — o-series reasoning
    "o4-mini": {"prompt_per_1k": 30, "completion_per_1k": 120},
    "o3": {"prompt_per_1k": 200, "completion_per_1k": 800},
    "o3-mini": {"prompt_per_1k": 40, "completion_per_1k": 160},
    # Anthropic Claude
    "claude-4.7-opus": {"prompt_per_1k": 250, "completion_per_1k": 1250},
    "claude-4.6-opus": {"prompt_per_1k": 200, "completion_per_1k": 1000},
    "claude-4.6-sonnet": {"prompt_per_1k": 60, "completion_per_1k": 300},
    "claude-4.5-sonnet": {"prompt_per_1k": 50, "completion_per_1k": 250},
    "claude-4.5-haiku": {"prompt_per_1k": 10, "completion_per_1k": 50},
    "claude-4.1-opus": {"prompt_per_1k": 180, "completion_per_1k": 900},
    # Legacy Claude aliases (billing continuity)
    "claude-3.5-sonnet": {"prompt_per_1k": 30, "completion_per_1k": 150},
    "claude-3-haiku": {"prompt_per_1k": 5, "completion_per_1k": 25},
    # Google Gemini
    "gemini-3.1-flash-lite": {"prompt_per_1k": 4, "completion_per_1k": 16},
    "gemini-2.5-flash": {"prompt_per_1k": 8, "completion_per_1k": 32},
    "gemini-2.5-flash-lite": {"prompt_per_1k": 3, "completion_per_1k": 12},
    # DeepSeek
    "deepseek-chat": {"prompt_per_1k": 3, "completion_per_1k": 12},
    "deepseek-reasoner": {"prompt_per_1k": 15, "completion_per_1k": 60},
    # GLM
    "glm-5.1": {"prompt_per_1k": 20, "completion_per_1k": 80},
    "glm-5": {"prompt_per_1k": 15, "completion_per_1k": 60},
    "glm-5-turbo": {"prompt_per_1k": 8, "completion_per_1k": 32},
    # Qwen
    "qwen-3.7-plus": {"prompt_per_1k": 12, "completion_per_1k": 48},
    "qwen-3.7-max": {"prompt_per_1k": 25, "completion_per_1k": 100},
    # Local / free
    "llama3": {"prompt_per_1k": 0, "completion_per_1k": 0},
    "llama-3.1-8b-instant": {"prompt_per_1k": 0, "completion_per_1k": 0},
    "llama-3.3-70b-versatile": {"prompt_per_1k": 0, "completion_per_1k": 0},
    "llama-3.2-3b-instruct": {"prompt_per_1k": 0, "completion_per_1k": 0},
    "openrouter/free": {"prompt_per_1k": 0, "completion_per_1k": 0},
}

_DEFAULT_CREDIT_PRICE: CreditModelPrice = {
    "prompt_per_1k": 10,
    "completion_per_1k": 30,
}

LLM_TX_TYPE = "llm_tokens"

# Explicit model → provider routing (longest-prefix match via normalize + this map).
MODEL_PROVIDER_MAP: dict[str, str] = {
    # OpenAI
    "gpt-5.5": "openai",
    "gpt-5.4": "openai",
    "gpt-5.4-mini": "openai",
    "gpt-5.4-nano": "openai",
    "gpt-5": "openai",
    "gpt-4.1": "openai",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "gpt-4-turbo": "openai",
    "gpt-3.5-turbo": "openai",
    "o4-mini": "openai",
    "o3": "openai",
    "o3-mini": "openai",
    # Anthropic
    "claude-4.7-opus": "anthropic",
    "claude-4.6-opus": "anthropic",
    "claude-4.6-sonnet": "anthropic",
    "claude-4.5-sonnet": "anthropic",
    "claude-4.5-haiku": "anthropic",
    "claude-4.1-opus": "anthropic",
    "claude-3.5-sonnet": "anthropic",
    "claude-3-haiku": "anthropic",
    # Google
    "gemini-3.1-flash-lite": "gemini",
    "gemini-2.5-flash": "gemini",
    "gemini-2.5-flash-lite": "gemini",
    # DeepSeek
    "deepseek-chat": "deepseek",
    "deepseek-reasoner": "deepseek",
    # GLM (OpenAI-compatible Zhipu endpoint)
    "glm-5.1": "glm",
    "glm-5": "glm",
    "glm-5-turbo": "glm",
    # Qwen (OpenAI-compatible DashScope / compatible endpoint)
    "qwen-3.7-plus": "qwen",
    "qwen-3.7-max": "qwen",
    # Local
    "llama3": "ollama",
    "llama-3.1-8b-instant": "groq",
    "llama-3.3-70b-versatile": "groq",
    "openrouter/free": "openrouter",
}

# Prefix heuristics when an exact registry key is missing.
_PROVIDER_PREFIX_RULES: Final[tuple[tuple[str, str], ...]] = (
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("claude-", "anthropic"),
    ("gemini-", "gemini"),
    ("deepseek-", "deepseek"),
    ("glm-", "glm"),
    ("qwen-", "qwen"),
    ("meta-llama/", "openrouter"),
    ("openrouter/", "openrouter"),
    ("llama-3.", "groq"),
    ("mixtral-", "groq"),
    ("gemma2-", "groq"),
    ("llama3", "ollama"),
)

DEFAULT_PROVIDER_ID: Final[str] = "openai"


def supported_models() -> list[str]:
    """Sorted catalog of models with explicit credit pricing."""
    return sorted(LLM_CREDIT_PRICING.keys())


def normalize_model_name(model_name: str | None) -> str:
    raw = (model_name or "").strip().lower()
    if not raw:
        return "gpt-4o-mini"
    # Longest key first so ``gpt-5.4-mini`` does not collapse to ``gpt-5.4`` / ``gpt-5``.
    for known in sorted(LLM_CREDIT_PRICING, key=len, reverse=True):
        if raw == known or raw.startswith(f"{known}-") or raw.startswith(f"{known}/"):
            return known
    return raw


def is_free_llm_model(model_name: str | None) -> bool:
    """True for Groq / OpenRouter ``:free`` / local models that must not debit wallets."""
    if bool(getattr(settings, "is_free_llm_route", False)):
        return True
    raw = (model_name or "").strip().lower()
    alias = (getattr(settings, "OPENAI_CHAT_MODEL", "") or "").strip().lower()
    if alias in {"openrouter/free", "free", "openrouter-free"}:
        return True
    if not raw:
        return False
    if raw.endswith(":free") or raw in {"openrouter/free", "free", "openrouter-free"}:
        return True
    price = LLM_CREDIT_PRICING.get(raw)
    if price and int(price["prompt_per_1k"]) == 0 and int(price["completion_per_1k"]) == 0:
        return True
    return False


def resolve_provider_for_model(model_name: str | None) -> str:
    """
    Map a chat model id to a gateway provider backend.

    Order: DB registry → exact pricing key → MODEL_PROVIDER_MAP → prefix heuristics → openai.
    """
    from app.services.llm_model_registry import get_cached_model

    cached = get_cached_model(model_name)
    if cached is not None and cached.is_active:
        return cached.provider

    key = normalize_model_name(model_name)
    if key in MODEL_PROVIDER_MAP:
        return MODEL_PROVIDER_MAP[key]
    raw = (model_name or "").strip().lower() or key
    if raw.endswith(":free") or raw.startswith("meta-llama/") or raw.startswith("openrouter/"):
        return "openrouter"
    for prefix, provider_id in sorted(_PROVIDER_PREFIX_RULES, key=lambda item: len(item[0]), reverse=True):
        if raw.startswith(prefix) or key.startswith(prefix):
            return provider_id
    return DEFAULT_PROVIDER_ID


def _price_for(model_name: str | None) -> CreditModelPrice:
    from app.services.llm_model_registry import get_cached_credit_price

    if is_free_llm_model(model_name):
        return {"prompt_per_1k": 0, "completion_per_1k": 0}

    db_price = get_cached_credit_price(model_name)
    if db_price is not None:
        return db_price

    key = normalize_model_name(model_name)
    if key in LLM_CREDIT_PRICING:
        return LLM_CREDIT_PRICING[key]
    # Settings-backed defaults for unknown models.
    return {
        "prompt_per_1k": int(
            getattr(settings, "LLM_CREDIT_PROMPT_PER_1K", _DEFAULT_CREDIT_PRICE["prompt_per_1k"])
        ),
        "completion_per_1k": int(
            getattr(
                settings,
                "LLM_CREDIT_COMPLETION_PER_1K",
                _DEFAULT_CREDIT_PRICE["completion_per_1k"],
            )
        ),
    }


def calculate_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    """
    Convert token usage into integer credit units (ceil per side).

    Formula per side: ``ceil(tokens / 1000 * rate_per_1k)`` with a minimum of
    1 credit on a side when that side used tokens and rate > 0.
    """
    price = _price_for(model_name)
    prompt = max(0, int(prompt_tokens))
    completion = max(0, int(completion_tokens))

    def _side(tokens: int, rate_per_1k: int) -> int:
        if tokens <= 0 or rate_per_1k <= 0:
            return 0
        # Integer ceil: (tokens * rate + 999) // 1000
        return max(1, (tokens * rate_per_1k + 999) // 1000)

    total = _side(prompt, int(price["prompt_per_1k"])) + _side(
        completion, int(price["completion_per_1k"])
    )
    multiplier = float(getattr(settings, "LLM_CREDIT_MULTIPLIER", 1.0) or 1.0)
    if multiplier != 1.0 and total > 0:
        total = max(1, int(round(total * multiplier)))
    return int(total)


def estimate_prompt_tokens(messages: list[dict[str, Any]] | None) -> int:
    """Rough token estimate (~4 chars/token) for preflight balance checks."""
    if not messages:
        return 1
    total_chars = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    total_chars += len(part["text"])
                elif isinstance(part, str):
                    total_chars += len(part)
        total_chars += 4  # role / framing overhead
    return max(1, (total_chars + 3) // 4)


def estimate_request_credits(
    model_name: str,
    messages: list[dict[str, Any]] | None,
    max_tokens: int,
) -> int:
    """Upper-bound credit estimate used to block empty wallets before vendor calls."""
    return calculate_cost(
        model_name,
        estimate_prompt_tokens(messages),
        max(1, int(max_tokens)),
    )
