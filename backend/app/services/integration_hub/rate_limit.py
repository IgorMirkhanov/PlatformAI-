"""Outbound Integration Hub rate limit — sliding window per connection_id.

CRM caps (architecture checklist §5):
  - Bitrix24: ≤ 2 req/s per connection_id
  - amoCRM:   ≤ 7 req/s per connection_id

Windows are isolated by Redis key ``ihub:rl:sw:{connection_id}`` so one tenant
cannot starve another.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from loguru import logger

from app.core.redis_client import get_redis_client

_PREFIX = "ihub:rl:"
_SW_PREFIX = "ihub:rl:sw:"
DEFAULT_LIMIT = 20
DEFAULT_WINDOW_SECONDS = 1.0

BITRIX_CONNECTION_RPS = 2
AMOCRM_CONNECTION_RPS = 7

ProviderKind = Literal["bitrix24", "amocrm", "kommo", "generic"]


class ConnectionRateLimited(Exception):
    """Raised when a tenant connection exceeds its outbound quota."""

    retry_after_seconds: float = 0.5

    def __init__(self, message: str, *, retry_after_seconds: float = 0.5) -> None:
        super().__init__(message)
        self.retry_after_seconds = float(retry_after_seconds)


_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local min_score = now - window
redis.call('ZREMRANGEBYSCORE', key, 0, min_score)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_after = window
  if oldest[2] then
    retry_after = math.max(0.01, window - (now - tonumber(oldest[2])))
  end
  return {0, count, retry_after}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window) + 1)
return {1, count + 1, 0}
"""


def _provider_limit(provider: str | None, limit: int | None) -> int:
    if limit is not None:
        return max(1, int(limit))
    key = (provider or "").strip().lower()
    if key == "bitrix24":
        return BITRIX_CONNECTION_RPS
    if key in {"amocrm", "kommo"}:
        return AMOCRM_CONNECTION_RPS
    return DEFAULT_LIMIT


def acquire_connection_slot(
    connection_id: uuid.UUID,
    *,
    limit: int | None = None,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    provider: str | None = None,
) -> None:
    """Sliding-window acquire. Fail-open if Redis is unavailable."""
    capped = _provider_limit(provider, limit)
    window = max(0.05, float(window_seconds))
    key = f"{_SW_PREFIX}{connection_id}"
    now = time.time()
    member = f"{now}:{uuid.uuid4()}"
    try:
        client = get_redis_client()
        try:
            result = client.eval(
                _SLIDING_WINDOW_LUA,
                1,
                key,
                str(now),
                str(window),
                str(capped),
                member,
            )
            allowed = int(result[0]) if result else 1
            retry_after = float(result[2]) if result and len(result) > 2 else window
            if allowed != 1:
                raise ConnectionRateLimited(
                    f"Outbound rate limit exceeded for connection {connection_id} "
                    f"({capped}/{window}s)",
                    retry_after_seconds=retry_after,
                )
            return
        except ConnectionRateLimited:
            raise
        except Exception:
            # Fallback: fixed window INCR (older Redis / no EVAL).
            fixed_key = f"{_PREFIX}{connection_id}"
            current = client.incr(fixed_key)
            if int(current) == 1:
                client.expire(fixed_key, max(1, int(window)))
            if int(current) > capped:
                raise ConnectionRateLimited(
                    f"Outbound rate limit exceeded for connection {connection_id}"
                )
    except ConnectionRateLimited:
        raise
    except Exception as exc:
        logger.warning(
            "IntegrationHub.rate_limit_unavailable | connection_id={id} error={error}",
            id=connection_id,
            error=str(exc),
        )


def acquire_bitrix_connection_slot(connection_id: uuid.UUID) -> None:
    acquire_connection_slot(
        connection_id,
        provider="bitrix24",
        limit=BITRIX_CONNECTION_RPS,
        window_seconds=1.0,
    )


def acquire_amocrm_connection_slot(connection_id: uuid.UUID) -> None:
    acquire_connection_slot(
        connection_id,
        provider="amocrm",
        limit=AMOCRM_CONNECTION_RPS,
        window_seconds=1.0,
    )


def wait_for_connection_slot(
    connection_id: uuid.UUID,
    *,
    provider: str = "bitrix24",
    limit: int | None = None,
    window_seconds: float = 1.0,
    timeout: float = 60.0,
) -> None:
    """Block until a slot is available (used by paced outbound / QA rate tests)."""
    deadline = time.monotonic() + max(0.1, float(timeout))
    while True:
        try:
            acquire_connection_slot(
                connection_id,
                provider=provider,
                limit=limit,
                window_seconds=window_seconds,
            )
            return
        except ConnectionRateLimited as exc:
            if time.monotonic() >= deadline:
                raise
            time.sleep(min(exc.retry_after_seconds, max(0.01, deadline - time.monotonic())))
