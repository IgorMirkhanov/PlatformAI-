"""Shared Redis helpers for SaaS runtime features (dedup, locks, cache)."""

from __future__ import annotations

from typing import Any, Final

from loguru import logger

from app.core.config import settings

WA_MSG_DEDUP_PREFIX: Final[str] = "wa:msg_dedup:"
WA_MSG_DEDUP_TTL_SECONDS: Final[int] = 24 * 60 * 60  # 24 hours
INBOUND_DEDUP_PREFIX: Final[str] = "inbound:dedup:"
INBOUND_DEDUP_TTL_SECONDS: Final[int] = 24 * 60 * 60
TELEGRAM_MSG_DEDUP_TTL_SECONDS: Final[int] = 24 * 60 * 60
FLOW_VERSION_PREFIX: Final[str] = "flow:published:ver:"
IMPERSONATION_REVOKE_PREFIX: Final[str] = "impersonation:revoked:"
IMPERSONATION_REVOKE_TTL_SECONDS: Final[int] = 60 * 60  # matches impersonation JWT TTL


def get_redis_client() -> Any:
    """Create a short-lived Redis client (decode_responses=True)."""
    import redis

    return redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=0.4,
        socket_timeout=0.6,
        decode_responses=True,
    )


def claim_telegram_inbound(
    *,
    update_id: str | int | None = None,
    bot_id: str | None = None,
    chat_id: str | None = None,
    message_id: str | int | None = None,
    message_text: str | None = None,
) -> bool:
    """
    Claim a Telegram inbound once across poller / webhook / worker races.

    Uses stable ``chat_id:message_id`` first (same user message can arrive under
    different ``update_id`` via message + business_message), then ``update_id``.
    """
    del message_text  # kept for call-site compatibility; not used for fingerprinting

    # 1) Stable Telegram message id (best — survives dual delivery envelopes).
    if bot_id and chat_id and message_id is not None and str(message_id).strip():
        if not claim_inbound_event(
            "telegram_msg",
            f"{bot_id}:{chat_id}:{message_id}",
            ttl_seconds=TELEGRAM_MSG_DEDUP_TTL_SECONDS,
        ):
            return False

    # 2) Update id (Telegram delivery envelope).
    if update_id is not None and str(update_id).strip():
        if not claim_inbound_event("telegram", str(update_id)):
            return False

    return True


async def get_async_redis() -> Any:
    """Create an async Redis client (decode_responses=True) for Flow sessions, etc."""
    import redis.asyncio as aioredis

    return aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=0.4,
        socket_timeout=1.0,
    )


def claim_whatsapp_message_id(
    message_id: str | None,
    *,
    ttl_seconds: int = WA_MSG_DEDUP_TTL_SECONDS,
) -> bool:
    """
    Atomically claim a WhatsApp ``message_id`` for processing.

    Returns
    -------
    True
        First sighting — caller should process the message.
    False
        Duplicate (already claimed) or empty id — caller should skip.
    """
    mid = (message_id or "").strip()
    if not mid:
        # No id → cannot dedup; allow processing to avoid dropping valid traffic.
        return True

    key = f"{WA_MSG_DEDUP_PREFIX}{mid}"
    try:
        client = get_redis_client()
        # SET NX EX — only the first writer wins.
        created = client.set(key, "1", nx=True, ex=max(60, int(ttl_seconds)))
        return bool(created)
    except Exception as exc:
        # Fail-open: never block inbound webhooks if Redis is down.
        logger.warning(
            "Redis.wa_dedup_unavailable | message_id={message_id} error={error}",
            message_id=mid[:64],
            error=str(exc),
        )
        return True


def claim_inbound_event(
    channel: str,
    event_id: str | None,
    *,
    ttl_seconds: int = INBOUND_DEDUP_TTL_SECONDS,
) -> bool:
    """
    Atomically claim a cross-channel inbound event id (Telegram update_id, IG mid, …).

    Returns True on first sighting, False on duplicate. Empty ids fail-open (True).
    """
    mid = (event_id or "").strip()
    if not mid:
        return True
    chan = (channel or "any").strip().lower() or "any"
    key = f"{INBOUND_DEDUP_PREFIX}{chan}:{mid}"
    try:
        client = get_redis_client()
        created = client.set(key, "1", nx=True, ex=max(60, int(ttl_seconds)))
        return bool(created)
    except Exception as exc:
        logger.warning(
            "Redis.inbound_dedup_unavailable | channel={channel} id={event_id} error={error}",
            channel=chan,
            event_id=mid[:64],
            error=str(exc),
        )
        return True


def bump_flow_cache_version(bot_id: str | Any) -> str:
    """Increment published-flow version so other workers drop stale local cache."""
    key = f"{FLOW_VERSION_PREFIX}{bot_id}"
    try:
        client = get_redis_client()
        ver = str(client.incr(key))
        client.expire(key, 7 * 24 * 60 * 60)
        return ver
    except Exception as exc:
        logger.warning(
            "Redis.flow_version_bump_failed | bot_id={bot_id} error={error}",
            bot_id=str(bot_id),
            error=str(exc),
        )
        return ""


def get_flow_cache_version(bot_id: str | Any) -> str | None:
    """Read current published-flow version; None when Redis unavailable."""
    key = f"{FLOW_VERSION_PREFIX}{bot_id}"
    try:
        client = get_redis_client()
        value = client.get(key)
        return str(value) if value is not None else "0"
    except Exception as exc:
        logger.warning(
            "Redis.flow_version_read_failed | bot_id={bot_id} error={error}",
            bot_id=str(bot_id),
            error=str(exc),
        )
        return None


def revoke_impersonation_jti(
    jti: str | None,
    *,
    ttl_seconds: int = IMPERSONATION_REVOKE_TTL_SECONDS,
) -> bool:
    """
    Mark an impersonation token ``jti`` as revoked until TTL elapses.

    Returns True when the denylist write succeeded.
    """
    token_id = (jti or "").strip()
    if not token_id:
        return False
    key = f"{IMPERSONATION_REVOKE_PREFIX}{token_id}"
    try:
        client = get_redis_client()
        client.set(key, "1", ex=max(60, int(ttl_seconds)))
        return True
    except Exception as exc:
        logger.error(
            "Redis.impersonation_revoke_failed | jti={jti} error={error}",
            jti=token_id[:64],
            error=str(exc),
        )
        return False


def is_impersonation_jti_revoked(jti: str | None) -> bool:
    """
    Return True when ``jti`` is on the impersonation denylist.

    Fail-closed in production if Redis is unreachable (reject the session).
    Fail-open in development so local work is not blocked by Redis.
    """
    token_id = (jti or "").strip()
    if not token_id:
        # Missing jti on impersonation JWT → treat as revoked in production.
        return bool(settings.is_production)

    key = f"{IMPERSONATION_REVOKE_PREFIX}{token_id}"
    try:
        client = get_redis_client()
        return bool(client.exists(key))
    except Exception as exc:
        logger.error(
            "Redis.impersonation_revoke_check_failed | jti={jti} error={error}",
            jti=token_id[:64],
            error=str(exc),
        )
        return bool(settings.is_production)


def impersonation_token_fingerprint(raw_token: str) -> str:
    """Stable denylist id for legacy ``imp_*`` tokens (no embedded jti)."""
    import hashlib

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def extract_cloud_whatsapp_message_ids(webhook_body: dict[str, Any]) -> list[str]:
    """Pull Meta Cloud API message ids (wamid.*) from a webhook payload."""
    ids: list[str] = []
    entries = webhook_body.get("entry") if isinstance(webhook_body, dict) else None
    if not isinstance(entries, list):
        return ids
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                mid = message.get("id")
                if mid:
                    ids.append(str(mid))
    return ids
