"""Shared exceptions and helpers for messenger outbound API failures."""

from __future__ import annotations

from typing import Final


AUTH_OR_FORBIDDEN_STATUSES: Final[frozenset[int]] = frozenset({401, 403})
RATE_LIMIT_STATUSES: Final[frozenset[int]] = frozenset({429})


class MessengerAPIError(Exception):
    """Raised when Telegram / WhatsApp Cloud API rejects an outbound request."""

    def __init__(
        self,
        *,
        channel: str,
        status_code: int | None,
        detail: str,
        retriable: bool = False,
    ) -> None:
        self.channel = channel
        self.status_code = status_code
        self.detail = detail
        self.retriable = retriable
        super().__init__(f"{channel} API error ({status_code}): {detail}")


def messenger_error_is_retriable(status_code: int | None) -> bool:
    """429 and 5xx are safe to retry; revoked tokens / auth failures are not."""
    if status_code is None:
        return True
    if status_code in AUTH_OR_FORBIDDEN_STATUSES:
        return False
    if status_code in RATE_LIMIT_STATUSES:
        return True
    return status_code >= 500


def format_messenger_diagnostic(
    *,
    channel: str,
    status_code: int | None,
    body: str,
) -> str:
    snippet = (body or "").strip().replace("\n", " ")[:800]
    code = status_code if status_code is not None else "unknown"
    return f"{channel} outbound failed (HTTP {code}): {snippet or 'no response body'}"
