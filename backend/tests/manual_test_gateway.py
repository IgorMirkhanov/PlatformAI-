#!/usr/bin/env python3
"""
Manual live check for ResilientLLMGateway (no pytest, real vendor API).

Usage (from repo root)::

    python backend/tests/manual_test_gateway.py
    python backend/tests/manual_test_gateway.py --model deepseek-chat

Requires a matching API key in ``backend/.env`` (loaded via ``app.core.config``).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure ``app`` package resolves when invoked as ``python backend/tests/...``.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.config import settings  # noqa: E402 — loads backend/.env on import
from app.services.llm.base import LLMProviderError  # noqa: E402
from app.services.llm.factory import LLMProviderFactory, get_llm_gateway  # noqa: E402
from app.services.llm.gateway import LLMGatewayError  # noqa: E402
from app.services.llm.pricing import (  # noqa: E402
    calculate_cost,
    estimate_request_credits,
    resolve_provider_for_model,
)

DEFAULT_PROMPT = (
    "Привет! Напиши одно предложение о готовности платформы MP.AI к работе."
)

_PROVIDER_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_AI_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "glm": ("GLM_API_KEY", "ZHIPU_API_KEY"),
    "qwen": ("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
}


def _env_value(name: str) -> str | None:
    value = getattr(settings, name, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _provider_configured(provider_id: str) -> bool:
    for key in _PROVIDER_ENV_KEYS.get(provider_id, ()):
        if _env_value(key):
            return True
    return False


def _pick_default_model() -> str:
    if _provider_configured("openai"):
        return "gpt-4o-mini"
    if _provider_configured("deepseek"):
        return "deepseek-chat"
    if _provider_configured("glm"):
        return "glm-5-turbo"
    if _provider_configured("qwen"):
        return "qwen-3.7-plus"
    return "gpt-4o-mini"


def _print_environment(model: str) -> None:
    preferred = resolve_provider_for_model(model)
    print("=== MP.AI LLM Gateway - manual live test ===")
    print(f"backend root : {_BACKEND_ROOT}")
    print(f"env file     : {_BACKEND_ROOT / '.env'} (exists={(_BACKEND_ROOT / '.env').exists()})")
    print(f"model        : {model}")
    print(f"routed to    : {preferred}")
    print("providers    :")
    for name in LLMProviderFactory.available():
        status = "configured" if _provider_configured(name) else "missing key"
        print(f"  - {name:10} [{status}]")
    print()


def _print_provider_status(gateway, model: str) -> None:
    preferred = resolve_provider_for_model(model)
    print("--- provider / circuit status ---")
    for provider in gateway.providers:
        pid = getattr(provider, "provider_id", type(provider).__name__)
        breaker = gateway.breaker_for(provider)
        marker = " <-- preferred" if str(pid).lower() == preferred else ""
        print(
            f"  {pid}: circuit={breaker.state.value}, "
            f"configured={_provider_configured(str(pid))}{marker}"
        )
    print()


async def _run(model: str, max_tokens: int) -> int:
    import app.services.llm.providers  # noqa: F401

    _print_environment(model)

    preferred = resolve_provider_for_model(model)
    if not _provider_configured(preferred):
        print(
            f"ERROR: No API key found for provider '{preferred}'.\n"
            f"Set one of {_PROVIDER_ENV_KEYS.get(preferred, ())} in backend/.env"
        )
        return 1

    gateway = get_llm_gateway(include_unconfigured=True)
    _print_provider_status(gateway, model)

    messages = [{"role": "user", "content": DEFAULT_PROMPT}]
    estimated_credits = estimate_request_credits(model, messages, max_tokens)
    print(f"estimated credits (preflight): {estimated_credits}")
    print("sending request...\n")

    try:
        response = await gateway.complete(
            messages,
            model=model,
            temperature=0.4,
            max_tokens=max_tokens,
        )
    except LLMGatewayError as exc:
        print("ERROR: all providers in the fallback chain failed.")
        print(f"  message   : {exc}")
        if exc.attempted:
            print(f"  attempted : {', '.join(exc.attempted)}")
        for index, failure in enumerate(exc.failures, start=1):
            print(f"  failure {index}: {type(failure).__name__}: {failure}")
        return 1
    except LLMProviderError as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        if exc.provider:
            print(f"  provider: {exc.provider}")
        return 1

    actual_credits = calculate_cost(
        response.model_name,
        response.prompt_tokens,
        response.completion_tokens,
    )

    print("=== response ===")
    print(response.content)
    print()
    print("=== usage ===")
    print(f"model_name         : {response.model_name}")
    print(f"prompt_tokens      : {response.prompt_tokens}")
    print(f"completion_tokens  : {response.completion_tokens}")
    print(f"total_tokens       : {response.total_tokens}")
    print(f"credits (estimate) : {actual_credits}")
    if response.raw:
        print(f"raw metadata       : {response.raw}")
    print()
    print("STATUS: OK - live LLM gateway call succeeded.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual live test for MP.AI LLM Gateway.")
    parser.add_argument(
        "--model",
        default=None,
        help="Chat model id (default: gpt-4o-mini if OPENAI_API_KEY set, else deepseek-chat).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=120,
        help="Max completion tokens (default: 120).",
    )
    args = parser.parse_args()
    model = (args.model or _pick_default_model()).strip()
    return asyncio.run(_run(model=model, max_tokens=args.max_tokens))


if __name__ == "__main__":
    raise SystemExit(main())
