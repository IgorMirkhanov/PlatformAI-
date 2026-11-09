"""Delayed follow-up messages when the client stays silent."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger

from app.core.celery_app import celery_app

FOLLOW_UP_TEXT = (
    "Здравствуйте! Не получил ответа. Подскажите, остались ли у вас вопросы? "
    "Я на связи и могу помочь."
)


def _redis_key(bot_id: str, chat_id: str) -> str:
    return f"mpai:follow_up:{bot_id}:{chat_id}"


def schedule_follow_up_message(
    *,
    bot_id: str,
    chat_id: str,
    client_id: str,
    delay_hours: int = 24,
) -> None:
    delay_seconds = max(3600, int(delay_hours) * 3600)
    try:
        from app.core.redis_client import get_redis_client

        redis = get_redis_client()
        previous = redis.get(_redis_key(bot_id, chat_id))
        if previous:
            celery_app.control.revoke(previous, terminate=False)
        async_result = send_follow_up_message.apply_async(
            kwargs={
                "bot_id": bot_id,
                "chat_id": chat_id,
                "client_id": client_id,
                "scheduled_at": datetime.now(UTC).isoformat(),
            },
            countdown=delay_seconds,
        )
        redis.setex(_redis_key(bot_id, chat_id), delay_seconds + 3600, async_result.id)
    except Exception as exc:
        logger.warning(
            "FollowUp.schedule_failed | bot_id={bot_id} chat_id={chat_id} error={error}",
            bot_id=bot_id,
            chat_id=chat_id,
            error=str(exc),
        )


@celery_app.task(name="app.tasks.follow_up_task.send_follow_up_message", bind=True, max_retries=2)
def send_follow_up_message(
    self,
    *,
    bot_id: str,
    chat_id: str,
    client_id: str,
    scheduled_at: str,
) -> dict[str, str]:
    return asyncio.run(
        _send_follow_up_async(
            bot_id=bot_id,
            chat_id=chat_id,
            client_id=client_id,
            scheduled_at=scheduled_at,
        )
    )


async def _send_follow_up_async(
    *,
    bot_id: str,
    chat_id: str,
    client_id: str,
    scheduled_at: str,
) -> dict[str, str]:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.models.core_models import Bot, ChatMessage
    from app.services.bot_message_extras import get_message_extras
    from app.services.telegram_service import telegram_service

    try:
        scheduled_dt = datetime.fromisoformat(scheduled_at)
        if scheduled_dt.tzinfo is None:
            scheduled_dt = scheduled_dt.replace(tzinfo=UTC)
    except ValueError:
        scheduled_dt = datetime.now(UTC) - timedelta(hours=1)

    async with async_session_factory() as db:
        bot = await db.get(Bot, uuid.UUID(bot_id))
        if bot is None or not bot.is_active:
            return {"status": "skipped", "reason": "bot_inactive"}

        extras = get_message_extras(bot)
        if not extras.get("follow_up_enabled"):
            return {"status": "skipped", "reason": "follow_up_disabled"}

        from app.services.flow_executor import FlowExecutor

        schedule_ok = FlowExecutor()._is_within_schedule(
            {
                "schedule_config": bot.schedule_config or {},
                "timezone": bot.timezone,
            }
        )
        if not schedule_ok:
            # Re-queue for one hour later so follow-ups respect working hours.
            send_follow_up_message.apply_async(
                kwargs={
                    "bot_id": bot_id,
                    "chat_id": chat_id,
                    "client_id": client_id,
                    "scheduled_at": scheduled_at,
                },
                countdown=3600,
            )
            return {"status": "deferred", "reason": "off_schedule"}

        latest = await db.scalar(
            select(ChatMessage)
            .where(ChatMessage.client_id == uuid.UUID(client_id))
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        if latest is not None:
            latest_at = latest.created_at
            if latest_at.tzinfo is None:
                latest_at = latest_at.replace(tzinfo=UTC)
            # User replied after we scheduled the follow-up.
            sender = str(getattr(latest.sender, "value", latest.sender)).upper()
            if sender == "CLIENT" and latest_at > scheduled_dt:
                return {"status": "skipped", "reason": "user_replied"}

        try:
            token = telegram_service.extract_bot_token(bot)
        except ValueError:
            return {"status": "skipped", "reason": "missing_token"}

        await telegram_service.send_message(
            bot_token=token,
            chat_id=chat_id,
            text=FOLLOW_UP_TEXT,
            buttons=[],
            bot_id=bot.id,
            client_id=uuid.UUID(client_id),
            db=db,
        )
        await db.commit()

    try:
        from app.core.redis_client import get_redis_client

        get_redis_client().delete(_redis_key(bot_id, chat_id))
    except Exception:
        pass

    logger.info(
        "FollowUp.sent | bot_id={bot_id} chat_id={chat_id}",
        bot_id=bot_id,
        chat_id=chat_id,
    )
    return {"status": "sent"}
