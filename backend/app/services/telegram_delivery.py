"""Remember when Telegram cannot deliver webhooks to this host.

setWebhook can succeed while Telegram's servers still time out on the public
URL. A new bot must not repeat that: once delivery has failed, later connects
use getUpdates and the poller pulls any update left pending.
"""

from __future__ import annotations

from loguru import logger

UNREACHABLE_KEY = "telegram:webhook_unreachable"

_UNREACHABLE_MARKERS = (
    "connection timed out",
    "connect timed out",
    "connection refused",
    "network is unreachable",
    "failed to resolve",
    "name or service not known",
    "ssl",
    "wrong response from the webhook",
    "bad webhook",
)


def error_means_unreachable(message: str | None) -> bool:
    text = (message or "").casefold()
    if not text:
        return False
    return any(marker in text for marker in _UNREACHABLE_MARKERS)


def webhook_delivery_blocked() -> bool:
    try:
        from app.core.redis_client import get_redis_client

        return bool(get_redis_client().get(UNREACHABLE_KEY))
    except Exception:
        return False


def note_webhook_failure(reason: str | None) -> None:
    if not error_means_unreachable(reason):
        return
    detail = (reason or "")[:180]
    try:
        from app.core.redis_client import get_redis_client

        get_redis_client().set(UNREACHABLE_KEY, detail)
    except Exception as exc:
        logger.warning(
            "TelegramDelivery.remember_failed | error={error}",
            error=type(exc).__name__,
        )
    logger.warning(
        "TelegramDelivery.webhook_unreachable | reason={reason}",
        reason=detail,
    )
