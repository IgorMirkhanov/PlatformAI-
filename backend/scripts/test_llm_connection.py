"""Smoke-test the configured LLM route (OpenRouter / Groq / OpenAI).

Sends one short chat completion through the same provider factory the API and
Celery workers use, so a green run means the platform itself can talk to the
model — not just that the key is syntactically valid.

Usage (from ``backend/`` or project root):
    python scripts/test_llm_connection.py
    python scripts/test_llm_connection.py --model openai/gpt-4o-mini
    python scripts/test_llm_connection.py --provider groq --prompt "Say hi"

Inside the running stack:
    docker compose -f docker-compose.prod.yml exec backend_api \
        python scripts/test_llm_connection.py

Exit codes: 0 = model replied, 1 = misconfigured or provider error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — allow ``python backend/scripts/test_llm_connection.py``
# from the repository root, or ``python scripts/test_llm_connection.py``
# from backend/.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _SCRIPT_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.llm.base import LLMProviderError  # noqa: E402
from app.services.llm.factory import (  # noqa: E402
    LLMProviderFactory,
    build_gateway_providers,
    get_llm_provider,
)
from app.services.llm.gateway import LLMGatewayError, ResilientLLMGateway  # noqa: E402

DEFAULT_PROMPT = "Ответь коротко: 'Тест OpenRouter успешно пройден'"
# Model id OpenRouter does not serve — makes the primary fail like a retired slug.
BROKEN_PRIMARY_MODEL = "meta-llama/llama-3.2-3b-instruct:free"

OK = "[OK]"
FAIL = "[FAIL]"
INFO = "[INFO]"


def _log(tag: str, msg: str) -> None:
    print(f"{tag} {msg}", flush=True)


def _mask(secret: str | None) -> str:
    """Show only enough of the key to identify it in logs."""
    raw = (secret or "").strip()
    if not raw:
        return "(not set)"
    if len(raw) <= 12:
        return f"{raw[:3]}…{raw[-2:]}"
    return f"{raw[:10]}…{raw[-4:]} (len={len(raw)})"


def _print_config(provider_id: str, model: str) -> None:
    print("── Resolved LLM configuration ──")
    print(f"  LLM_PROVIDER          : {settings.LLM_PROVIDER}")
    print(f"  resolved provider id  : {provider_id}")
    print(f"  OPENAI_CHAT_MODEL     : {settings.OPENAI_CHAT_MODEL}")
    print(f"  resolved chat model   : {settings.resolved_chat_model}")
    print(f"  request model         : {model}")
    print(f"  base_url              : {settings.resolved_openai_base_url}")
    print(f"  OPENAI_API_KEY        : {_mask(settings.OPENAI_API_KEY)}")
    print(f"  OPENROUTER_API_KEY    : {_mask(getattr(settings, 'OPENROUTER_API_KEY', None))}")
    print(f"  GROQ_API_KEY          : {_mask(getattr(settings, 'GROQ_API_KEY', None))}")
    print(f"  free route (no debit) : {settings.is_free_llm_route}")
    print(f"  fallback provider     : {getattr(settings, 'FALLBACK_LLM_PROVIDER', None)}")
    print(f"  fallback model        : {getattr(settings, 'FALLBACK_LLM_MODEL', None)}")
    print(f"  registered providers  : {', '.join(LLMProviderFactory.available())}")
    print()


def _print_chain(providers: list) -> None:
    print("── Gateway fallback chain ──")
    for index, provider in enumerate(providers):
        role = "primary" if index == 0 else f"fallback #{index}"
        print(
            f"  {index}. {provider.provider_id:<12} {role:<12} "
            f"model={getattr(provider, 'model', None)} "
            f"key={'yes' if getattr(provider, 'api_key', None) else 'NO'}"
        )
    print()


async def run_check(
    *,
    provider_id: str | None,
    model: str | None,
    prompt: str,
    max_tokens: int,
) -> int:
    resolved_provider = LLMProviderFactory.resolve_provider_id(provider_id)
    provider = get_llm_provider(resolved_provider)
    request_model = (model or getattr(provider, "model", None) or "").strip()

    _print_config(resolved_provider, request_model)

    if not getattr(provider, "api_key", None):
        _log(
            FAIL,
            f"Provider '{resolved_provider}' has no API key. "
            "Set OPENAI_API_KEY / OPENROUTER_API_KEY in .env and restart.",
        )
        return 1

    _log(INFO, f"Prompt: {prompt}")
    started = time.perf_counter()
    try:
        response = await provider.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_tokens,
            model=request_model or None,
        )
    except LLMProviderError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _log(
            FAIL,
            f"{type(exc).__name__} after {elapsed_ms:.0f} ms "
            f"(provider={getattr(exc, 'provider', resolved_provider)}, "
            f"status={getattr(exc, 'status_code', None)}): {exc}",
        )
        return 1
    except Exception as exc:  # noqa: BLE001 — surface anything the adapter missed
        elapsed_ms = (time.perf_counter() - started) * 1000
        _log(FAIL, f"Unexpected {type(exc).__name__} after {elapsed_ms:.0f} ms: {exc}")
        return 1

    elapsed_ms = (time.perf_counter() - started) * 1000
    text = (response.content or "").strip()

    print("── Response ──")
    print(f"  status        : HTTP 200 / content received")
    print(f"  provider      : {response.provider}")
    print(f"  model         : {response.model_name}")
    print(f"  latency       : {elapsed_ms:.0f} ms")
    print(f"  prompt tokens : {response.prompt_tokens}")
    print(f"  output tokens : {response.completion_tokens}")
    print(f"  finish reason : {(response.raw or {}).get('finish_reason')}")
    print(f"  text          : {text or '(empty)'}")
    print()

    if not text:
        _log(FAIL, "Provider answered with empty content — check model availability.")
        return 1

    _log(OK, f"LLM route is alive: {response.provider} / {response.model_name}")
    return 0


async def run_fallback_check(*, prompt: str, max_tokens: int) -> int:
    """
    Break the primary vendor on purpose and assert the fallback answers.

    The primary provider is pinned to a model OpenRouter no longer serves, which
    raises the same error class as a 429 / 5xx / timeout. A pass means the chain
    switched vendors *and* remapped the model to the fallback's own id.
    """
    gateway = ResilientLLMGateway(build_gateway_providers(include_unconfigured=True))
    providers = gateway.effective_chain()
    _print_chain(providers)

    if len(providers) < 2:
        _log(FAIL, "Only one provider in the chain — nothing to fall back to.")
        return 1

    primary = providers[0]
    expected_provider = (
        str(getattr(settings, "FALLBACK_LLM_PROVIDER", "") or "").lower()
        or providers[1].provider_id
    )
    fallback = next(
        (p for p in providers[1:] if p.provider_id == expected_provider),
        None,
    )
    if fallback is None:
        _log(FAIL, f"Fallback provider '{expected_provider}' is not in the chain.")
        return 1
    if not getattr(fallback, "api_key", None):
        _log(
            FAIL,
            f"Fallback provider '{fallback.provider_id}' has no API key — set "
            f"{fallback.provider_id.upper()}_API_KEY in .env, otherwise every "
            "OpenRouter outage becomes a failed reply.",
        )
        return 1
    if providers[1] is not fallback:
        _log(
            FAIL,
            f"Chain order wrong: expected {expected_provider} right after "
            f"{primary.provider_id}, got {providers[1].provider_id}.",
        )
        return 1

    # Pin the primary to a slug OpenRouter rejects; leave the fallback untouched.
    primary.model = BROKEN_PRIMARY_MODEL
    _log(
        INFO,
        f"Simulating outage: {primary.provider_id} pinned to '{BROKEN_PRIMARY_MODEL}' "
        f"(retired slug → 404), fallback = {fallback.provider_id} / {fallback.model}",
    )

    started = time.perf_counter()
    try:
        response = await gateway.complete(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
    except LLMGatewayError as exc:
        _log(FAIL, f"Whole chain failed: {exc}")
        return 1
    elapsed_ms = (time.perf_counter() - started) * 1000

    text = (response.content or "").strip()
    print("── Fallback response ──")
    print(f"  answered by   : {response.provider}")
    print(f"  model         : {response.model_name}")
    print(f"  latency       : {elapsed_ms:.0f} ms (includes the failed primary call)")
    print(f"  text          : {text or '(empty)'}")
    print()

    if response.provider == primary.provider_id:
        _log(FAIL, "Primary answered — the outage simulation did not take effect.")
        return 1
    if response.provider != fallback.provider_id:
        _log(
            FAIL,
            f"Unexpected vendor '{response.provider}' answered instead of "
            f"'{fallback.provider_id}'.",
        )
        return 1
    if not text:
        _log(FAIL, f"Fallback '{response.provider}' returned empty content.")
        return 1

    _log(
        OK,
        f"Fallback works: {primary.provider_id} failed -> {response.provider} "
        f"answered with {response.model_name}",
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one test completion through the configured LLM provider."
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override provider id (openrouter, groq, openai…). Default: LLM_PROVIDER.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override model id. Default: settings.resolved_chat_model.",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to send.")
    # Reasoning models (gpt-oss, nemotron) spend output tokens on hidden reasoning
    # and return empty content when the cap is too low — keep headroom.
    parser.add_argument("--max-tokens", type=int, default=300, help="Response cap.")
    parser.add_argument(
        "--test-fallback",
        action="store_true",
        help="Force the primary provider to fail and verify the fallback answers.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.test_fallback:
        print("=== MP.AI — LLM fallback test (simulated primary outage) ===\n")
        return asyncio.run(
            run_fallback_check(prompt=args.prompt, max_tokens=args.max_tokens)
        )

    print("=== MP.AI — LLM connection test ===\n")
    return asyncio.run(
        run_check(
            provider_id=args.provider,
            model=args.model,
            prompt=args.prompt,
            max_tokens=args.max_tokens,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
