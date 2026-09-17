"""Runtime gates for Control-tab policies (spam, keywords, auto-resume)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot, ChatMessage, Client, MessageSender
from app.services.bot_control_config import (
    auto_resume_timedelta,
    get_control_config,
    phrase_matches,
)

_SPAM_KEY = "mpai:spam:{client_id}"
_PAUSE_AT_KEY = "mpai:operator_pause_at:{client_id}"


async def _redis() -> Any | None:
    try:
        from app.core.redis_client import get_async_redis

        return await get_async_redis()
    except Exception as exc:
        logger.debug("BotControlGate.redis_unavailable | error={error}", error=str(exc))
        return None


async def mark_operator_paused(client_id: uuid.UUID) -> None:
    client = await _redis()
    if client is None:
        return
    key = _PAUSE_AT_KEY.format(client_id=client_id)
    try:
        await client.set(key, datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.debug("BotControlGate.pause_mark_failed | error={error}", error=str(exc))


async def clear_operator_paused_mark(client_id: uuid.UUID) -> None:
    client = await _redis()
    if client is None:
        return
    try:
        await client.delete(_PAUSE_AT_KEY.format(client_id=client_id))
    except Exception:
        pass


async def maybe_auto_resume(
    db: AsyncSession,
    *,
    bot: Bot,
    client: Client,
) -> str | None:
    """Resume AI if auto-resume window elapsed. Returns optional resume message."""
    if not client.is_paused_by_operator:
        return None
    control = get_control_config(bot)
    op = control["operator_intervention"]
    if not op.get("auto_resume_enabled"):
        return None
    delta = auto_resume_timedelta(control)
    if delta.total_seconds() <= 0:
        return None

    paused_at: datetime | None = None
    redis = await _redis()
    if redis is not None:
        try:
            raw = await redis.get(_PAUSE_AT_KEY.format(client_id=client.id))
            if raw:
                paused_at = datetime.fromisoformat(
                    raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
                )
        except Exception:
            paused_at = None

    if paused_at is None:
        result = await db.execute(
            select(ChatMessage.created_at)
            .where(
                ChatMessage.client_id == client.id,
                ChatMessage.sender == MessageSender.OPERATOR,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        paused_at = result.scalar_one_or_none()

    if paused_at is None:
        return None
    if paused_at.tzinfo is None:
        paused_at = paused_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) < paused_at + delta:
        return None

    client.is_paused_by_operator = False
    if getattr(client, "conversation_status", None) == "escalated":
        client.conversation_status = "active"
    await clear_operator_paused_mark(client.id)
    await db.flush()
    logger.info(
        "BotControlGate.auto_resumed | client_id={client_id} bot_id={bot_id}",
        client_id=client.id,
        bot_id=bot.id,
    )
    if op.get("resume_message_enabled"):
        text = str(op.get("resume_message") or "").strip()
        return text or None
    return None


async def apply_keyword_gates(
    db: AsyncSession,
    *,
    bot: Bot,
    client: Client,
    message_text: str,
) -> None:
    control = get_control_config(bot)
    kw = control["keyword_dialog"]
    if kw.get("resume_enabled") and phrase_matches(message_text, kw.get("resume_phrases") or []):
        if client.is_paused_by_operator:
            client.is_paused_by_operator = False
            if getattr(client, "conversation_status", None) == "escalated":
                client.conversation_status = "active"
            await clear_operator_paused_mark(client.id)
            await db.flush()
            logger.info(
                "BotControlGate.keyword_resume | client_id={client_id}",
                client_id=client.id,
            )
        return

    if kw.get("stop_enabled") and phrase_matches(message_text, kw.get("stop_phrases") or []):
        if not client.is_paused_by_operator:
            client.is_paused_by_operator = True
            await mark_operator_paused(client.id)
            await db.flush()
            logger.info(
                "BotControlGate.keyword_stop | client_id={client_id}",
                client_id=client.id,
            )


async def check_spam_limit(
    *,
    bot: Bot,
    client_id: uuid.UUID,
) -> str | None:
    """Return throttle reply text when spam limit is hit, else None."""
    control = get_control_config(bot)
    spam = control["spam_protection"]
    if not spam.get("enabled"):
        return None
    redis = await _redis()
    if redis is None:
        return None
    key = _SPAM_KEY.format(client_id=client_id)
    window = int(spam.get("duration_seconds") or 10)
    limit = int(spam.get("message_count") or 5)
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        if count > limit:
            return str(spam.get("limit_message") or "").strip() or None
    except Exception as exc:
        logger.debug("BotControlGate.spam_check_failed | error={error}", error=str(exc))
    return None


async def should_pause_on_operator_message(
    db: AsyncSession,
    *,
    bot: Bot,
    client: Client,
    message_text: str,
) -> bool:
    control = get_control_config(bot)
    op = control["operator_intervention"]
    if not op.get("pause_on_operator_message"):
        return False
    if op.get("exception_phrases_enabled") and phrase_matches(
        message_text, op.get("exception_phrases") or []
    ):
        return False
    if op.get("ignore_first_operator_message"):
        result = await db.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(
                ChatMessage.client_id == client.id,
                ChatMessage.sender == MessageSender.OPERATOR,
            )
        )
        prior = int(result.scalar_one() or 0)
        # Current message is already flushed in some paths; treat 0/1 as "first".
        if prior <= 1:
            return False
    return True
