"""Step 1.1 — LLM Gateway adapter / factory tests (mocked OpenAI SDK)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.llm.base import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
)
from app.services.llm.factory import LLMProviderFactory, get_llm_provider
from app.services.llm.providers.openai_provider import OpenAIProvider


def _openai_http_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return httpx.Response(status_code, request=request)


def _fake_openai_response(
    *,
    content: str = "Hello",
    prompt_tokens: int = 12,
    completion_tokens: int = 7,
    model: str = "gpt-4o",
    tool_calls: list[Any] | None = None,
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(
        id="chatcmpl-test",
        model=model,
        choices=[choice],
        usage=usage,
    )


@pytest.fixture
def mock_openai_client() -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_fake_openai_response(content="Hi from mock")
    )
    return client


@pytest.mark.asyncio
async def test_openai_provider_complete_maps_response(mock_openai_client: MagicMock) -> None:
    provider = OpenAIProvider(api_key="sk-test", client=mock_openai_client, model="gpt-4o")
    messages = [{"role": "user", "content": "ping"}]
    tools = [
        {
            "name": "lookup",
            "description": "Lookup something",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    result = await provider.complete(
        messages,
        tools=tools,
        temperature=0.2,
        max_tokens=128,
    )

    assert isinstance(result, LLMResponse)
    assert result.content == "Hi from mock"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 7
    assert result.model_name == "gpt-4o"
    assert result.tool_calls is None

    call_kwargs = mock_openai_client.chat.completions.create.await_args.kwargs
    assert call_kwargs["model"] == "gpt-4o"
    assert call_kwargs["messages"] == messages
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_tokens"] == 128
    assert call_kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Lookup something",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


@pytest.mark.asyncio
async def test_openai_provider_maps_token_usage(mock_openai_client: MagicMock) -> None:
    mock_openai_client.chat.completions.create = AsyncMock(
        return_value=_fake_openai_response(
            content="ok",
            prompt_tokens=100,
            completion_tokens=42,
            model="gpt-4o-mini",
        )
    )
    provider = OpenAIProvider(api_key="sk-test", client=mock_openai_client)

    result = await provider.complete([{"role": "user", "content": "count tokens"}])

    assert result.prompt_tokens == 100
    assert result.completion_tokens == 42
    assert result.total_tokens == 142
    assert result.model_name == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_openai_provider_translates_rate_limit_error(
    mock_openai_client: MagicMock,
) -> None:
    from openai import RateLimitError

    mock_openai_client.chat.completions.create = AsyncMock(
        side_effect=RateLimitError(
            message="Rate limit hit",
            response=_openai_http_response(429),
            body={"error": {"message": "Rate limit hit"}},
        )
    )
    provider = OpenAIProvider(api_key="sk-test", client=mock_openai_client)

    with pytest.raises(LLMRateLimitError) as exc_info:
        await provider.complete([{"role": "user", "content": "x"}])

    assert exc_info.value.provider == "openai"
    assert isinstance(exc_info.value, LLMProviderError)


@pytest.mark.asyncio
async def test_openai_provider_translates_auth_error(mock_openai_client: MagicMock) -> None:
    from openai import AuthenticationError

    mock_openai_client.chat.completions.create = AsyncMock(
        side_effect=AuthenticationError(
            message="Invalid API key",
            response=_openai_http_response(401),
            body={"error": {"message": "Invalid API key"}},
        )
    )
    provider = OpenAIProvider(api_key="sk-test", client=mock_openai_client)

    with pytest.raises(LLMAuthenticationError):
        await provider.complete([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_openai_provider_translates_generic_api_error(
    mock_openai_client: MagicMock,
) -> None:
    from openai import APIStatusError

    mock_openai_client.chat.completions.create = AsyncMock(
        side_effect=APIStatusError(
            message="Server error",
            response=_openai_http_response(500),
            body={"error": {"message": "Server error"}},
        )
    )
    provider = OpenAIProvider(api_key="sk-test", client=mock_openai_client)

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.complete([{"role": "user", "content": "x"}])

    assert exc_info.value.status_code == 500
    assert not isinstance(exc_info.value, LLMRateLimitError)
    assert not isinstance(exc_info.value, LLMAuthenticationError)


def test_factory_returns_openai_by_string_id(mock_openai_client: MagicMock) -> None:
    # Ensure built-in adapters are registered.
    import app.services.llm.providers  # noqa: F401

    provider = LLMProviderFactory.create("openai", api_key="sk-test", client=mock_openai_client)
    assert isinstance(provider, BaseLLMProvider)
    assert isinstance(provider, OpenAIProvider)
    assert provider.provider_id == "openai"
    assert "openai" in LLMProviderFactory.available()


def test_get_llm_provider_convenience(mock_openai_client: MagicMock) -> None:
    provider = get_llm_provider("openai", api_key="sk-test", client=mock_openai_client)
    assert isinstance(provider, OpenAIProvider)


def test_factory_unknown_provider_raises() -> None:
    import app.services.llm.providers  # noqa: F401

    with pytest.raises(LLMProviderError) as exc_info:
        LLMProviderFactory.create("not-a-real-vendor")
    assert "Unknown LLM provider" in str(exc_info.value)


def test_factory_register_extensibility() -> None:
    """Future vendors can register without editing factory internals."""

    @LLMProviderFactory.register("fake-vendor")
    class FakeVendorProvider(BaseLLMProvider):
        provider_id = "fake-vendor"

        async def complete(
            self,
            messages: list[dict],
            tools: list[dict] | None = None,
            temperature: float = 0.7,
            max_tokens: int = 1000,
            **kwargs: Any,
        ) -> LLMResponse:
            return LLMResponse(
                content="fake",
                tool_calls=None,
                prompt_tokens=1,
                completion_tokens=1,
                model_name="fake-1",
            )

    try:
        provider = LLMProviderFactory.create("fake-vendor")
        assert isinstance(provider, FakeVendorProvider)
        assert "fake-vendor" in LLMProviderFactory.available()
    finally:
        LLMProviderFactory._registry.pop("fake-vendor", None)
