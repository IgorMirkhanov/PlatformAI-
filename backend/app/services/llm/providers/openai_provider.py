"""OpenAI chat adapter — maps SDK responses to vendor-neutral LLMResponse."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from app.core.config import settings
from app.services.llm.base import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)
from app.services.llm.factory import LLMProviderFactory


def _map_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Normalize tool schemas into OpenAI Chat Completions ``tools`` format."""
    if not tools:
        return None
    mapped: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            mapped.append(tool)
            continue
        # Accept bare function schemas: {name, description, parameters}
        if "name" in tool:
            mapped.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description") or "",
                        "parameters": tool.get("parameters")
                        or tool.get("input_schema")
                        or {"type": "object", "properties": {}},
                    },
                }
            )
            continue
        if "function" in tool and isinstance(tool["function"], dict):
            mapped.append({"type": "function", "function": tool["function"]})
    return mapped or None


def _tool_calls_from_message(message: Any) -> list[dict[str, Any]] | None:
    raw_calls = getattr(message, "tool_calls", None) or None
    if not raw_calls:
        return None
    out: list[dict[str, Any]] = []
    for call in raw_calls:
        fn = getattr(call, "function", None)
        out.append(
            {
                "id": getattr(call, "id", None),
                "type": getattr(call, "type", None) or "function",
                "function": {
                    "name": getattr(fn, "name", None) if fn is not None else None,
                    "arguments": getattr(fn, "arguments", None) if fn is not None else None,
                },
            }
        )
    return out or None


def _translate_openai_error(
    exc: BaseException,
    *,
    model: str,
    provider_id: str = "openai",
) -> LLMProviderError:
    """Map OpenAI SDK exceptions → gateway errors (no SDK types escape)."""
    label = provider_id or "openai"
    try:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            AuthenticationError,
            PermissionDeniedError,
            RateLimitError,
            APIStatusError,
        )
    except ImportError:  # pragma: no cover
        return LLMProviderError(str(exc), provider=label, cause=exc)

    if isinstance(exc, AuthenticationError) or isinstance(exc, PermissionDeniedError):
        return LLMAuthenticationError(
            str(exc) or f"{label} authentication failed.",
            provider=label,
            status_code=getattr(exc, "status_code", 401),
            cause=exc,
        )
    if isinstance(exc, RateLimitError):
        return LLMRateLimitError(
            str(exc) or f"{label} rate limit exceeded.",
            provider=label,
            status_code=getattr(exc, "status_code", 429) or 429,
            cause=exc,
        )
    if isinstance(exc, APITimeoutError):
        return LLMTimeoutError(
            str(exc) or f"{label} request timed out.",
            provider=label,
            cause=exc,
        )
    if isinstance(exc, APIConnectionError):
        return LLMProviderError(
            str(exc) or f"{label} connection error.",
            provider=label,
            cause=exc,
        )
    if isinstance(exc, APIStatusError):
        code = int(getattr(exc, "status_code", 0) or 0)
        if code == 401 or code == 403:
            return LLMAuthenticationError(
                str(exc),
                provider=label,
                status_code=code,
                cause=exc,
            )
        if code == 429:
            return LLMRateLimitError(
                str(exc),
                provider=label,
                status_code=code,
                cause=exc,
            )
        return LLMProviderError(
            str(exc),
            provider=label,
            status_code=code or None,
            cause=exc,
        )

    # Malformed / truncated JSON bodies from proxies, Ollama, OpenRouter, etc.
    import json

    if isinstance(exc, (json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError)):
        return LLMInvalidResponseError(
            f"{label} returned an invalid or incomplete response: {exc}",
            provider=label,
            status_code=502,
            cause=exc,
        )
    return LLMProviderError(str(exc), provider=label, cause=exc)


@LLMProviderFactory.register("openai")
class OpenAIProvider(BaseLLMProvider):
    """Async OpenAI Chat Completions adapter (SDK 1.x+)."""

    provider_id = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        client: Any | None = None,
        base_url: str | None = None,
        provider_id: str | None = None,
    ) -> None:
        if provider_id:
            self.provider_id = provider_id
        self.api_key = api_key if api_key is not None else settings.OPENAI_API_KEY
        resolved_base = (
            (base_url or "").strip()
            or (getattr(settings, "resolved_openai_base_url", None) or "")
            or (getattr(settings, "OPENAI_BASE_URL", None) or "")
        ).strip() or None
        self.base_url = resolved_base
        self.model = (
            model
            or getattr(settings, "resolved_chat_model", None)
            or getattr(settings, "OPENAI_CHAT_MODEL", None)
            or "gpt-4o"
        ).strip() or "gpt-4o"
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 20.0)
        )
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise LLMAuthenticationError(
                f"{self.provider_id.upper()}_API_KEY is not configured."
                if self.provider_id != "openai"
                else "OPENAI_API_KEY is not configured.",
                provider=self.provider_id,
                status_code=401,
            )
        from openai import AsyncOpenAI

        kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": self.timeout_seconds,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        model = str(kwargs.pop("model", None) or self.model)
        openai_tools = _map_openai_tools(tools)
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if openai_tools is not None:
            request["tools"] = openai_tools
            if "tool_choice" in kwargs:
                request["tool_choice"] = kwargs.pop("tool_choice")
        # Forward a small allow-list of OpenAI extras without leaking unknown kwargs blindly.
        for key in ("response_format", "user", "seed", "top_p", "stop"):
            if key in kwargs and kwargs[key] is not None:
                request[key] = kwargs.pop(key)

        client = self._get_client()
        logger.debug(
            "OpenAIProvider.complete | model={model} messages={n} tools={tools}",
            model=model,
            n=len(messages),
            tools=len(openai_tools or []),
        )
        try:
            response = await client.chat.completions.create(
                **request,
                timeout=self.timeout_seconds,
            )
        except LLMProviderError:
            raise
        except Exception as exc:
            raise _translate_openai_error(
                exc, model=model, provider_id=self.provider_id
            ) from exc

        try:
            choices = getattr(response, "choices", None) or []
            if not choices:
                raise LLMInvalidResponseError(
                    f"{self.provider_id} returned empty choices "
                    f"(invalid or incomplete JSON payload).",
                    provider=self.provider_id,
                    status_code=502,
                )
            choice = choices[0]
            message = getattr(choice, "message", None)
            if message is None:
                raise LLMInvalidResponseError(
                    f"{self.provider_id} response missing message content.",
                    provider=self.provider_id,
                    status_code=502,
                )
            content = (getattr(message, "content", None) or "").strip()
            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
            completion_tokens = (
                int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
            )
            resolved_model = getattr(response, "model", None) or model
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMInvalidResponseError(
                f"{self.provider_id} returned an invalid or incomplete response: {exc}",
                provider=self.provider_id,
                status_code=502,
                cause=exc,
            ) from exc

        return LLMResponse(
            content=content,
            tool_calls=_tool_calls_from_message(message),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model_name=str(resolved_model),
            provider=self.provider_id,
            raw={
                "id": getattr(response, "id", None),
                "finish_reason": getattr(choice, "finish_reason", None),
            },
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream content deltas from OpenAI (text only for Step 1.1)."""
        model = str(kwargs.pop("model", None) or self.model)
        openai_tools = _map_openai_tools(tools)
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if openai_tools is not None:
            request["tools"] = openai_tools

        client = self._get_client()
        try:
            stream = await client.chat.completions.create(
                **request,
                timeout=self.timeout_seconds,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    yield text
        except LLMProviderError:
            raise
        except Exception as exc:
            raise _translate_openai_error(
                exc, model=model, provider_id=self.provider_id
            ) from exc
