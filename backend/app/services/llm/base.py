"""Provider-agnostic LLM Gateway — base protocol, response model, errors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMResponse:
    """Vendor-neutral chat completion result."""

    content: str
    tool_calls: list[dict[str, Any]] | None
    prompt_tokens: int
    completion_tokens: int
    model_name: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    # Set True after Gateway / Orchestrator settles wallet debit once.
    billing_handled: bool = False
    # Vendor that actually produced this response (set by gateway / adapter).
    provider: str | None = None

    @property
    def total_tokens(self) -> int:
        return int(self.prompt_tokens) + int(self.completion_tokens)


class LLMProviderError(Exception):
    """Base error for LLM Gateway adapters (never leak vendor SDK types upward)."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.cause = cause


class LLMRateLimitError(LLMProviderError):
    """Provider returned HTTP 429 / rate limit."""


class LLMAuthenticationError(LLMProviderError):
    """Missing or invalid API credentials."""


class LLMTimeoutError(LLMProviderError):
    """Request timed out talking to the provider."""


class LLMInvalidResponseError(LLMProviderError):
    """Provider returned malformed / incomplete JSON or an unusable payload."""


class InsufficientCreditsForLLMError(LLMProviderError):
    """
    Organization wallet cannot cover the LLM request (HTTP 402 semantics).

    Raised on preflight when balance is too low — vendor must not be called.
    """

    def __init__(
        self,
        message: str = "Insufficient credits for LLM request.",
        *,
        organization_id: object | None = None,
        balance: int | None = None,
        required: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, provider=None, status_code=402, cause=cause)
        self.organization_id = organization_id
        self.balance = balance
        self.required = required


class BaseLLMProvider(ABC):
    """
    Adapter contract for chat LLMs.

    Callers (bots, agents, Flow Builder) must depend only on this interface —
    never on OpenAI / Anthropic / Gemini SDKs.
    """

    provider_id: str = "base"

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a single non-streaming chat completion."""

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Stream text deltas (optional for Step 1.1).

        Default implementation raises — providers override when ready.
        Declared so call sites can type against the interface early.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement streaming yet."
        )
        if False:  # pragma: no cover
            yield ""

    async def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Architecture-spec alias around ``complete``."""
        extra = dict(kwargs)
        if model is not None:
            extra["model"] = model
        if timeout is not None:
            extra["timeout_seconds"] = timeout
        return await self.complete(messages, **extra)
