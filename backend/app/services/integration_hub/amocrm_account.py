"""amoCRM account rate limit (official integration cap).

Docs (https://www.amocrm.ru/developers/content/api/recommendations, checked 2026-08):
  - not more than 7 requests per second per integration
  - up to 50 requests per second per account (all integrations combined)
  Over limit → HTTP 429; repeated abuse → HTTP 403 and account API block.

We throttle at 7 req/s per amoCRM account (subdomain) so this integration never
trips the documented cap. 429 responses are retried with exponential backoff
in the adapter, not by spinning past the bucket.
"""

from __future__ import annotations

from loguru import logger

from app.core.redis_client import get_redis_client

_PREFIX = "ihub:amo:account:"
# Official per-integration cap.
AMOCRM_INTEGRATION_RPS = 7
AMOCRM_ACCOUNT_WINDOW_SECONDS = 1


class AmoCRMAccountRateLimited(Exception):
    """Account already used its 7 req/s budget — backoff / retry."""

    retry_after_seconds: float = 1.0


def account_rate_key(subdomain: str | None, connection_id: str | None) -> str:
    host = (subdomain or "").strip().lower()
    host = host.replace("https://", "").replace("http://", "").rstrip("/")
    return host or (connection_id or "unknown").strip().lower()


def acquire_amocrm_account_slot(account_key: str, *, limit: int = AMOCRM_INTEGRATION_RPS) -> None:
    """Fail-open if Redis is down; fail-closed on quota."""
    key = f"{_PREFIX}{account_key}"
    try:
        client = get_redis_client()
        current = client.incr(key)
        if int(current) == 1:
            client.expire(key, AMOCRM_ACCOUNT_WINDOW_SECONDS)
        if int(current) > max(1, int(limit)):
            raise AmoCRMAccountRateLimited(
                f"amoCRM account rate limit ({limit}/s) exceeded for {account_key}"
            )
    except AmoCRMAccountRateLimited:
        raise
    except Exception as exc:
        logger.warning(
            "amoCRM.account_rate_limit_unavailable | account={account} error={error}",
            account=account_key,
            error=type(exc).__name__,
        )
