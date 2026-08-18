"""Low-level OpenAI chat client with strict request timeouts."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings
from app.services.llm.types import LLMCompletion, wrap_if_transient

_openai_clients: dict[tuple[str, float, str | None], Any] = {}
_client_lock = asyncio.Lock()


async def _get_openai_client(
    *,
    api_key: str,
    timeout_seconds: float,
    base_url: str | None = None,
) -> Any:
    """Reuse AsyncOpenAI + HTTP connection pool across requests."""
    from openai import AsyncOpenAI

    normalized_base = (base_url or "").strip() or None
    cache_key = (api_key, timeout_seconds, normalized_base)
    client = _openai_clients.get(cache_key)
    if client is not None:
        return client

    async with _client_lock:
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
    ) -> LLMCompletion:
        api_key = (
            settings.OPENAI_API_KEY
            or getattr(settings, "OPENROUTER_API_KEY", None)
            or getattr(settings, "GROQ_API_KEY", None)
        )
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        client = await _get_openai_client(
            api_key=api_key,
            timeout_seconds=self.timeout_seconds,
            base_url=getattr(settings, "resolved_openai_base_url", None),
        )
        logger.debug(
            "LLMClient.openai_request | model={model} timeout={timeout}s messages={count}",
            model=model,
            timeout=self.timeout_seconds,
            count=len(messages),
        )
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "timeout": self.timeout_seconds,
            }
            if tools:
                kwargs["tools"] = tools
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            wrapped = wrap_if_transient(exc, model=model)
            if wrapped is not exc:
                raise wrapped from exc
            raise

        content = response.choices[0].message.content
        if not content:
            tool_calls = getattr(response.choices[0].message, "tool_calls", None) or []
            if tool_calls:
                names = [str(getattr(tc.function, "name", "") or "") for tc in tool_calls]
                content = f"Called tools: {', '.join(filter(None, names)) or 'function'}"
            else:
                raise RuntimeError(f"OpenAI model '{model}' returned an empty completion")

        usage = response.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(
            getattr(usage, "total_tokens", input_tokens + output_tokens) or 0
        )
        return LLMCompletion(
            text=content.strip(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
