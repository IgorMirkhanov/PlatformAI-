"""Bitrix24 portal leaky-bucket (mass-market cloud REST limits).

Docs (https://apidocs.bitrix24.com/limits.html, checked 2026-08):
  leaky bucket per Bitrix24 portal (not global, not per-app globally):
  - non-Enterprise: Y = 2 req/s, block threshold X = 50
  - Enterprise:     Y = 5 req/s, block threshold X = 250
  Over limit → HTTP 503 / error QUERY_LIMIT_EXCEEDED.

We cap at 2 req/s per portal so typical client tariffs never trip the bucket.
When the slot is taken, callers MUST enqueue (Celery), not retry in a hot loop.
"""

from __future__ import annotations

from loguru import logger

from app.core.redis_client import get_redis_client

_PREFIX = "ihub:b24:portal:"
# Official non-Enterprise leaky-bucket drain rate.
BITRIX_PORTAL_RPS = 2
BITRIX_PORTAL_WINDOW_SECONDS = 1


class BitrixPortalRateLimited(Exception):
    """Portal already used its 2 req/s budget — enqueue / countdown retry."""

    retry_after_seconds: float = 1.0


def portal_rate_key(member_id: str | None, domain: str | None, connection_id: str | None) -> str:
    return (member_id or domain or connection_id or "unknown").strip().lower()


def acquire_bitrix_portal_slot(portal_key: str, *, limit: int = BITRIX_PORTAL_RPS) -> None:
    """Fail-open if Redis is down (CRM must not brick); fail-closed on quota."""
    key = f"{_PREFIX}{portal_key}"
    try:
        client = get_redis_client()
        current = client.incr(key)
        if int(current) == 1:
            client.expire(key, BITRIX_PORTAL_WINDOW_SECONDS)
        if int(current) > max(1, int(limit)):
            raise BitrixPortalRateLimited(
                f"Bitrix24 portal rate limit ({limit}/s) exceeded for {portal_key}"
            )
    except BitrixPortalRateLimited:
        raise
    except Exception as exc:
        logger.warning(
            "Bitrix24.portal_rate_limit_unavailable | portal={portal} error={error}",
            portal=portal_key,
            error=type(exc).__name__,
        )
