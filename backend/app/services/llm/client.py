"""Low-level OpenAI chat client with strict request timeouts."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings
from app.services.llm.types import LLMCompletion, wrap_if_transient

_openai_clients: dict[tuple[str, float, str | None], Any] = {}
_client_lock: asyncio.Lock | None = None
_openai_clients_loop: asyncio.AbstractEventLoop | None = None


def _openai_lock() -> asyncio.Lock:
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def aclose_cached_openai_clients() -> None:
    """Close pooled AsyncOpenAI/httpx clients bound to a previous event loop."""
    global _openai_clients, _client_lock, _openai_clients_loop
    clients = list(_openai_clients.values())
    _openai_clients = {}
    _openai_clients_loop = None
    _client_lock = None
    for client in clients:
        close = getattr(client, "close", None)
        if close is None:
            continue
        try:
            result = close()
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                await result
        except Exception:
            continue


async def _get_openai_client(
    *,
    api_key: str,
    timeout_seconds: float,
    base_url: str | None = None,
) -> Any:
    """Reuse AsyncOpenAI + HTTP connection pool across requests."""
    global _openai_clients_loop
    from openai import AsyncOpenAI

    normalized_base = (base_url or "").strip() or None
    cache_key = (api_key, timeout_seconds, normalized_base)
    loop = asyncio.get_running_loop()
    if _openai_clients and _openai_clients_loop is not None and _openai_clients_loop is not loop:
        await aclose_cached_openai_clients()

    client = _openai_clients.get(cache_key)
    if client is not None:
        return client

    async with _openai_lock():
        client = _openai_clients.get(cache_key)
        if client is not None:
            return client
        http_client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=50,
                keepalive_expiry=30.0,
            ),
            timeout=timeout_seconds,
        )
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": timeout_seconds,
            "http_client": http_client,
        }
        if normalized_base:
            kwargs["base_url"] = normalized_base
        client = AsyncOpenAI(**kwargs)
        _openai_clients[cache_key] = client
        _openai_clients_loop = loop
        return client


class OpenAIChatClient:
    """Thin AsyncOpenAI wrapper — always applies ``timeout`` on the client."""

    def __init__(self, *, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 20.0)
        )

    async def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.4,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMCompletion:
        model_l = (model or "").strip().lower()
        # Prefer vendor-native credentials when the model clearly belongs there.
        # Otherwise OPENAI_BASE_URL=openrouter + missing max_tokens → 402 (65536 default).
        if api_key is None and model_l.startswith("gemini"):
            api_key = getattr(settings, "GEMINI_API_KEY", None) or None
            if base_url is None and api_key:
                base_url = (
                    getattr(settings, "GEMINI_BASE_URL", None)
                    or "https://generativelanguage.googleapis.com/v1beta/openai/"
                )
        elif api_key is None and (
            model_l.startswith("openai/gpt-oss")
            or model_l.startswith("llama")
            or model_l.startswith("mixtral")
        ):
            api_key = getattr(settings, "GROQ_API_KEY", None) or None
            if base_url is None and api_key:
                base_url = getattr(settings, "GROQ_BASE_URL", None) or "https://api.groq.com/openai/v1"

        resolved_key = (
            api_key
            or settings.OPENAI_API_KEY
            or getattr(settings, "OPENROUTER_API_KEY", None)
            or getattr(settings, "GROQ_API_KEY", None)
        )
        if not resolved_key:
            raise RuntimeError("OPENAI_API_KEY / OPENROUTER_API_KEY / GROQ_API_KEY is not configured")

        resolved_base = (
            base_url
            if base_url is not None
            else getattr(settings, "resolved_openai_base_url", None)
        )
        # Hard cap — OpenRouter treats omitted max_tokens as ~65536 and 402s on low balance.
        resolved_max_tokens = int(
            max_tokens
            if max_tokens is not None
            else getattr(settings, "LLM_MAX_OUTPUT_TOKENS", 2048)
            or 2048
        )
        resolved_max_tokens = max(64, min(resolved_max_tokens, 4096))

        client = await _get_openai_client(
            api_key=resolved_key,
            timeout_seconds=self.timeout_seconds,
            base_url=resolved_base,
        )
        logger.debug(
            "LLMClient.openai_request | model={model} timeout={timeout}s messages={count} "
            "base={base} max_tokens={max_tokens}",
            model=model,
            timeout=self.timeout_seconds,
            count=len(messages),
            base=(resolved_base or "default"),
            max_tokens=resolved_max_tokens,
        )
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": resolved_max_tokens,
                "timeout": self.timeout_seconds,
            }
            if tools:
                kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
            # Gemini 3.x rejects temperature on the OpenAI-compat endpoint.
            if model_l.startswith("gemini-3"):
                kwargs.pop("temperature", None)
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            wrapped = wrap_if_transient(exc, model=model)
            if wrapped is not exc:
                raise wrapped from exc
            raise

        content = response.choices[0].message.content
        message = response.choices[0].message
        tool_calls_raw = getattr(message, "tool_calls", None) or []
        tool_calls: list[dict[str, Any]] | None = None
        if tool_calls_raw:
            tool_calls = []
            for tc in tool_calls_raw:
                fn = getattr(tc, "function", None)
                if fn is None:
                    continue
                tool_calls.append(
                    {
                        "id": getattr(tc, "id", None),
                        "name": str(getattr(fn, "name", "") or ""),
                        "arguments": str(getattr(fn, "arguments", "") or "{}"),
                    }
                )
        if not content and not tool_calls:
            raise RuntimeError(f"OpenAI model '{model}' returned an empty completion")
        # Tool-only turns must keep empty content — never synthesize "Called tools: …"
        # (that string used to leak into Telegram/Wazzup when ReAct resolution was skipped).

        usage = response.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(
            getattr(usage, "total_tokens", input_tokens + output_tokens) or 0
        )
        return LLMCompletion(
            text=(content or "").strip(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            tool_calls=tool_calls,
            raw_message=message,
        )
