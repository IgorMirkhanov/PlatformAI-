"""Shared LLM types and transient-error classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class LLMFailureKind(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    CONNECTION = "connection"
    OTHER = "other"


@dataclass(slots=True)
class LLMCompletion:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    used_fallback: bool = False
    used_platform_fallback: bool = False
    primary_model: str | None = None
    fallback_model: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    raw_message: Any = None
    tools_executed: list[str] | None = None
    booking_tools_succeeded: bool = False


class TransientLLMError(Exception):
    """Provider error that is safe to retry / fall back on."""

    def __init__(
        self,
        message: str,
        *,
        kind: LLMFailureKind = LLMFailureKind.OTHER,
        status_code: int | None = None,
        model: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.model = model
        self.cause = cause


def classify_provider_exception(exc: BaseException) -> tuple[bool, LLMFailureKind, int | None]:
    """
    Return ``(is_transient, kind, status_code)`` for OpenAI / httpx-style errors.

    Transient = timeout, connection, 429, 500, 503 (and related 5xx).
    """
    # Prefer typed OpenAI SDK exceptions when available.
    try:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            APIStatusError,
        )
    except ImportError:  # pragma: no cover
        APIConnectionError = APITimeoutError = RateLimitError = APIStatusError = ()  # type: ignore[misc, assignment]

    if isinstance(exc, APITimeoutError):
        return True, LLMFailureKind.TIMEOUT, None
    if isinstance(exc, RateLimitError):
        status = getattr(exc, "status_code", None) or 429
        return True, LLMFailureKind.RATE_LIMIT, int(status)
    if isinstance(exc, APIConnectionError):
        return True, LLMFailureKind.CONNECTION, None
    if isinstance(exc, APIStatusError):
        code = int(getattr(exc, "status_code", 0) or 0)
        if code == 429:
            return True, LLMFailureKind.RATE_LIMIT, code
        if code in {500, 502, 503, 504} or code >= 500:
            return True, LLMFailureKind.SERVER_ERROR, code
        return False, LLMFailureKind.OTHER, code

    # httpx timeouts / connection errors (Ollama path, etc.)
    try:
        import httpx

        if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
            return True, LLMFailureKind.TIMEOUT, None
        if isinstance(exc, httpx.NetworkError):
            return True, LLMFailureKind.CONNECTION, None
        if isinstance(exc, httpx.HTTPStatusError):
            code = int(exc.response.status_code)
            if code == 429:
                return True, LLMFailureKind.RATE_LIMIT, code
            if code in {500, 502, 503, 504} or code >= 500:
                return True, LLMFailureKind.SERVER_ERROR, code
            return False, LLMFailureKind.OTHER, code
    except ImportError:  # pragma: no cover
        pass

    message = str(exc).lower()
    if any(token in message for token in ("timeout", "timed out", "deadline exceeded")):
        return True, LLMFailureKind.TIMEOUT, None
    if any(token in message for token in ("rate limit", "429", "too many requests")):
        return True, LLMFailureKind.RATE_LIMIT, 429
    if any(token in message for token in ("503", "500", "502", "504", "server error", "overloaded")):
        return True, LLMFailureKind.SERVER_ERROR, None
    if any(token in message for token in ("connection", "connect error", "network")):
        return True, LLMFailureKind.CONNECTION, None
    return False, LLMFailureKind.OTHER, None


def wrap_if_transient(exc: BaseException, *, model: str | None = None) -> BaseException:
    """Re-raise as ``TransientLLMError`` when the failure is retryable."""
    if isinstance(exc, TransientLLMError):
        return exc
    is_transient, kind, status = classify_provider_exception(exc)
    if not is_transient:
        return exc
    return TransientLLMError(
        str(exc),
        kind=kind,
        status_code=status,
        model=model,
        cause=exc,
    )


SAFE_USER_FALLBACK_MESSAGE = (
    "К сожалению, сервис временно перегружен. Попробуйте написать чуть позже."
)


def format_execution_failure_message(
    *,
    provider_error: str,
    primary_model: str | None = None,
    fallback_model: str | None = None,
    extras: dict[str, Any] | None = None,
) -> str:
    """Structured diagnostic text: level + action + provider detail."""
    parts = [
        "level=ERROR",
        "action=LLM_EXECUTION_FAILURE",
        f"primary_model={primary_model or '-'}",
        f"fallback_model={fallback_model or '-'}",
        f"provider_error={provider_error[:3500]}",
    ]
    if extras:
        for key, value in extras.items():
            parts.append(f"{key}={value}")
    return " | ".join(parts)
