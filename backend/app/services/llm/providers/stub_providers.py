"""Placeholder + OpenAI-compatible vendor adapters for the LLM gateway."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider, LLMProviderError, LLMResponse
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.openai_provider import OpenAIProvider


class _UnconfiguredProvider(BaseLLMProvider):
    """Shared stub — registry membership without calling external APIs."""

    provider_id = "stub"
    _label = "stub"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        raise LLMProviderError(
            f"LLM provider '{self._label}' is registered but not configured.",
            provider=self._label,
        )


@LLMProviderFactory.register("anthropic")
class AnthropicProvider(_UnconfiguredProvider):
    provider_id = "anthropic"
    _label = "anthropic"


@LLMProviderFactory.register("gemini")
class GeminiProvider(_UnconfiguredProvider):
    provider_id = "gemini"
    _label = "gemini"


@LLMProviderFactory.register("ollama")
class OllamaProvider(_UnconfiguredProvider):
    provider_id = "ollama"
    _label = "ollama"


@LLMProviderFactory.register("deepseek")
class DeepSeekProvider(OpenAIProvider):
    """DeepSeek Chat Completions via OpenAI-compatible API."""

    provider_id = "deepseek"

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
        super().__init__(
            api_key=api_key
            if api_key is not None
            else getattr(settings, "DEEPSEEK_API_KEY", None),
            model=model
            or getattr(settings, "DEEPSEEK_CHAT_MODEL", None)
            or "deepseek-chat",
            timeout_seconds=timeout_seconds,
            client=client,
            base_url=base_url
            or getattr(settings, "DEEPSEEK_BASE_URL", None)
            or "https://api.deepseek.com",
            provider_id=provider_id or "deepseek",
        )


@LLMProviderFactory.register("glm")
class GLMProvider(OpenAIProvider):
    """Zhipu GLM via OpenAI-compatible endpoint."""

    provider_id = "glm"

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
        super().__init__(
            api_key=api_key
            if api_key is not None
            else getattr(settings, "GLM_API_KEY", None),
            model=model or getattr(settings, "GLM_CHAT_MODEL", None) or "glm-5-turbo",
            timeout_seconds=timeout_seconds,
            client=client,
            base_url=base_url
            or getattr(settings, "GLM_BASE_URL", None)
            or "https://open.bigmodel.cn/api/paas/v4",
            provider_id=provider_id or "glm",
        )


@LLMProviderFactory.register("qwen")
class QwenProvider(OpenAIProvider):
    """Qwen via OpenAI-compatible DashScope (or compatible) endpoint."""

    provider_id = "qwen"

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
        super().__init__(
            api_key=api_key
            if api_key is not None
            else getattr(settings, "QWEN_API_KEY", None),
            model=model
            or getattr(settings, "QWEN_CHAT_MODEL", None)
            or "qwen-3.7-plus",
            timeout_seconds=timeout_seconds,
            client=client,
            base_url=base_url
            or getattr(settings, "QWEN_BASE_URL", None)
            or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_id=provider_id or "qwen",
        )


@LLMProviderFactory.register("groq")
class GroqProvider(OpenAIProvider):
    """Groq Chat Completions via OpenAI-compatible API (free-tier models)."""

    provider_id = "groq"

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
        super().__init__(
            api_key=api_key
            if api_key is not None
            else getattr(settings, "GROQ_API_KEY", None),
            model=model
            or getattr(settings, "GROQ_CHAT_MODEL", None)
            or "openai/gpt-oss-20b",
            timeout_seconds=timeout_seconds,
            client=client,
            base_url=base_url
            or getattr(settings, "GROQ_BASE_URL", None)
            or "https://api.groq.com/openai/v1",
            provider_id=provider_id or "groq",
        )


@LLMProviderFactory.register("openrouter")
class OpenRouterProvider(OpenAIProvider):
    """OpenRouter via OpenAI-compatible endpoint (supports ``:free`` models)."""

    provider_id = "openrouter"

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
        super().__init__(
            api_key=api_key
            if api_key is not None
            else getattr(settings, "OPENROUTER_API_KEY", None)
            or getattr(settings, "OPENAI_API_KEY", None),
            model=model or getattr(settings, "resolved_chat_model", None) or "gpt-4o-mini",
            timeout_seconds=timeout_seconds,
            client=client,
            base_url=base_url
            or getattr(settings, "OPENROUTER_BASE_URL", None)
            or getattr(settings, "OPENAI_BASE_URL", None)
            or "https://openrouter.ai/api/v1",
            provider_id=provider_id or "openrouter",
        )
