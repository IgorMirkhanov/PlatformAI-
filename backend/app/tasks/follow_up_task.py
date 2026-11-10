"""Delayed follow-up messages when the client stays silent."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.celery_app import celery_app
from app.core.database import run_celery_async

FOLLOW_UP_TEXT = (
    "Здравствуйте! Не получил ответа. Подскажите, остались ли у вас вопросы? "
    "Я на связи и могу помочь."
)

_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _redis_key(bot_id: str, chat_id: str) -> str:
    return f"mpai:follow_up:{bot_id}:{chat_id}"


def _state_key(bot_id: str, chat_id: str) -> str:
    return f"mpai:follow_up_state:{bot_id}:{chat_id}"


def _get_redis():
    from app.core.redis_client import get_redis_client

    return get_redis_client()


def cancel_follow_up_message(*, bot_id: str, chat_id: str) -> None:
    """Revoke pending follow-up and reset dialogue chain counters."""
    try:
        redis = _get_redis()
        key = _redis_key(bot_id, chat_id)
        previous = redis.get(key)
        if previous:
            celery_app.control.revoke(previous, terminate=False)
        redis.delete(key)
        redis.delete(_state_key(bot_id, chat_id))
    except Exception as exc:
        logger.warning(
            "FollowUp.cancel_failed | bot_id={bot_id} chat_id={chat_id} error={error}",
            bot_id=bot_id,
            chat_id=chat_id,
            error=str(exc),
        )


def _load_state(bot_id: str, chat_id: str) -> dict[str, Any]:
    try:
        raw = _get_redis().get(_state_key(bot_id, chat_id))
        if not raw:
            return {"sent_count": 0, "chain_done": False}
        data = json.loads(raw)
        if isinstance(data, dict):
            return {
                "sent_count": int(data.get("sent_count") or 0),
                "chain_done": bool(data.get("chain_done")),
            }
    except Exception:
        pass
    return {"sent_count": 0, "chain_done": False}


def _save_state(
    bot_id: str,
    chat_id: str,
    *,
    sent_count: int,
    chain_done: bool,
    ttl_seconds: int,
) -> None:
    try:
        _get_redis().setex(
            _state_key(bot_id, chat_id),
            max(ttl_seconds, 3600),
            json.dumps(
                {"sent_count": sent_count, "chain_done": chain_done},
                ensure_ascii=False,
            ),
        )
    except Exception:
        pass


def _store_task_id(
    bot_id: str, chat_id: str, task_id: str, *, ttl_seconds: int
) -> None:
    try:
        _get_redis().setex(
            _redis_key(bot_id, chat_id),
            max(ttl_seconds + 3600, 3600),
            task_id,
        )
    except Exception:
        pass


def seconds_until_next_schedule_window(
    schedule_config: dict[str, Any] | None,
    *,
    timezone_name: str | None = None,
) -> int | None:
    """
    Seconds until the next open schedule window start.

    Returns ``None`` when schedule is disabled / empty (always open).
    Returns ``0`` when currently inside a window.
    """
    schedule = schedule_config if isinstance(schedule_config, dict) else {}
    if not schedule.get("enabled"):
        return None
    windows = schedule.get("windows") or []
    if not windows:
        return None

    tz_name = (
        str(schedule.get("timezone") or timezone_name or "Asia/Almaty").strip()
        or "Asia/Almaty"
    )
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)

    normalized: list[tuple[int, str, str]] = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        day = str(window.get("day") or "").lower()
        if day not in _WEEKDAYS:
            continue
        start = str(window.get("start") or "00:00")
        end = str(window.get("end") or "23:59")
        day_idx = _WEEKDAYS.index(day)
        normalized.append((day_idx, start, end))
    if not normalized:
        return None

    current_day = now.weekday()  # Monday=0
    current_hm = now.strftime("%H:%M")
    for day_idx, start, end in normalized:
        if day_idx == current_day and start <= current_hm <= end:
            return 0

    best: datetime | None = None
    for offset in range(0, 8):
        day = (current_day + offset) % 7
        for day_idx, start, end in normalized:
            if day_idx != day:
                continue
            try:
                hour, minute = [int(part) for part in start.split(":", 1)]
            except ValueError:
                continue
            candidate_date = (now + timedelta(days=offset)).date()
            candidate = datetime(
                candidate_date.year,
                candidate_date.month,
                candidate_date.day,
                hour,
                minute,
                tzinfo=tz,
            )
            if candidate <= now:
                continue
            if best is None or candidate < best:
                best = candidate
    if best is None:
        return 3600
    return max(60, int((best - now).total_seconds()))


def schedule_follow_up_message(
    *,
    bot_id: str,
    chat_id: str,
    client_id: str,
    delay_seconds: int | None = None,
    delay_hours: int | None = None,
    sent_count: int = 0,
    force: bool = False,
    channel: str = "telegram",
) -> None:
    """
    Arm (or re-arm) a silence follow-up for this chat.

    ``force`` is used for next-in-chain scheduling after a successful send.
    """
    from app.services.bot_message_extras import follow_up_delay_seconds

    if delay_seconds is None:
        if delay_hours is not None:
            delay_seconds = max(60, int(delay_hours) * 3600)
        else:
            delay_seconds = follow_up_delay_seconds(None)
    delay_seconds = max(60, int(delay_seconds))

    try:
        redis = _get_redis()
        state = _load_state(bot_id, chat_id)
        if not force and state.get("chain_done"):
            logger.info(
                "FollowUp.skip_arm_chain_done | bot_id={bot_id} chat_id={chat_id}",
                bot_id=bot_id,
                chat_id=chat_id,
            )
            return

        previous = redis.get(_redis_key(bot_id, chat_id))
        if previous:
            celery_app.control.revoke(previous, terminate=False)

        async_result = send_follow_up_message.apply_async(
            kwargs={
                "bot_id": bot_id,
                "chat_id": chat_id,
                "client_id": client_id,
                "scheduled_at": datetime.now(UTC).isoformat(),
                "sent_count": int(sent_count),
                "channel": (channel or "telegram").strip().lower() or "telegram",
            },
            countdown=delay_seconds,
        )
        _store_task_id(
            bot_id, chat_id, async_result.id, ttl_seconds=delay_seconds
        )
        _save_state(
            bot_id,
            chat_id,
            sent_count=int(sent_count),
            chain_done=False,
            ttl_seconds=delay_seconds + 7 * 86400,
        )
        logger.info(
            "FollowUp.scheduled | bot_id={bot_id} chat_id={chat_id} "
            "delay_s={delay} sent_count={sent}",
            bot_id=bot_id,
            chat_id=chat_id,
            delay=delay_seconds,
            sent=sent_count,
        )
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
    sent_count: int = 0,
    channel: str = "telegram",
) -> dict[str, str]:
    return run_celery_async(
        _send_follow_up_async(
            bot_id=bot_id,
            chat_id=chat_id,
            client_id=client_id,
            scheduled_at=scheduled_at,
            sent_count=int(sent_count or 0),
            channel=(channel or "telegram").strip().lower() or "telegram",
        )
    )


async def _compose_follow_up_text(
    *,
    bot: Any,
    client_id: uuid.UUID,
    db: Any,
    instructions: str,
) -> str:
    instructions = (instructions or "").strip()
    if not instructions:
        return FOLLOW_UP_TEXT

    # Prefer a short LLM reply guided by instructions + recent dialogue.
    try:
        from sqlalchemy import select

        from app.models.core_models import ChatMessage, MessageSender
        from app.services.llm_orchestrator import llm_orchestrator

        rows = (
            await db.scalars(
                select(ChatMessage)
                .where(ChatMessage.client_id == client_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(8)
            )
        ).all()
        history_lines: list[str] = []
        for row in reversed(list(rows)):
            sender = str(getattr(row.sender, "value", row.sender)).upper()
            role = "Клиент" if sender == "CLIENT" else "Бот"
            text = (row.message_text or "").strip()
            if text:
                history_lines.append(f"{role}: {text[:400]}")
        history_block = "\n".join(history_lines) or "(история пуста)"

        model = str(getattr(bot, "llm_model_name", None) or "gpt-4o-mini")
        temperature = float(getattr(bot, "llm_temperature", 0.4) or 0.4)
        completion = await llm_orchestrator.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Ты follow-up сообщения бота. Клиент молчит. "
                        "Напиши одно короткое сообщение на русском по инструкции. "
                        "Без markdown, без tool calls, 1–3 предложения."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Инструкция follow-up:\n{instructions}\n\n"
                        f"Недавний диалог:\n{history_block}"
                    ),
                },
            ],
            model=model,
            temperature=min(temperature, 0.5),
            bot_id=getattr(bot, "id", None),
            client_id=client_id,
            db=db,
            tools=None,
            degrade_on_exhaustion=True,
        )
        text = (completion.text or "").strip()
        if text:
            return text[:2000]
    except Exception as exc:
        logger.warning(
            "FollowUp.llm_compose_failed | bot_id={bot_id} error={error}",
            bot_id=getattr(bot, "id", None),
            error=str(exc),
        )
    # Fall back to instructions as a static template, then default.
    return instructions[:2000] if instructions else FOLLOW_UP_TEXT


async def _persist_follow_up_message(
    db: Any,
    *,
    client_id: uuid.UUID,
    text: str,
) -> None:
    from app.models.core_models import ChatMessage, MessageSender

    db.add(
        ChatMessage(
            client_id=client_id,
            sender=MessageSender.BOT,
            message_text=text,
            payload={"is_follow_up": True, "source": "follow_up_task"},
        )
    )


async def _deliver_channel_text(
    db: Any,
    *,
    bot: Any,
    channel: str,
    chat_id: str,
    client_id: uuid.UUID,
    text: str,
) -> None:
    channel_l = (channel or "telegram").lower()
    if channel_l in {"whatsapp", "whatsapp_cloud"}:
        from app.core.security import decrypt_credential
        from app.services.whatsapp_service import whatsapp_service

        credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
        channels = (
            credentials.get("channels")
            if isinstance(credentials.get("channels"), dict)
            else {}
        )
        wa = channels.get("whatsapp") if isinstance(channels.get("whatsapp"), dict) else {}
        access_token_enc = (
            credentials.get("whatsapp_access_token")
            or credentials.get("access_token")
            or wa.get("access_token")
        )
        phone_number_id = (
            credentials.get("phone_number_id")
            or credentials.get("whatsapp_phone_number_id")
            or wa.get("phone_number_id")
        )
        if not access_token_enc or not phone_number_id:
            raise ValueError("whatsapp_credentials_missing")
        token = decrypt_credential(str(access_token_enc))
        await whatsapp_service.send_text_message(
            access_token=token,
            phone_number_id=str(phone_number_id),
            recipient=chat_id,
            text=text,
            bot_id=bot.id,
            client_id=client_id,
            db=db,
        )
        return

    if channel_l in {"whatsapp_qr", "whatsapp-qr"}:
        from app.services.whatsapp_qr_service import whatsapp_qr_service

        await whatsapp_qr_service.send_text_message(
            bot_id=bot.id,
            to=chat_id,
            text=text,
        )
        return

    from app.services.telegram_service import telegram_service

    token = telegram_service.extract_bot_token(bot)
    await telegram_service.send_message(
        bot_token=token,
        chat_id=chat_id,
        text=text,
        buttons=[],
        bot_id=bot.id,
        client_id=client_id,
        db=db,
    )


async def _send_follow_up_async(
    *,
    bot_id: str,
    chat_id: str,
    client_id: str,
    scheduled_at: str,
    sent_count: int,
    channel: str = "telegram",
) -> dict[str, str]:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.models.core_models import Bot, ChatMessage
    from app.services.bot_message_extras import (
        follow_up_delay_seconds,
        get_message_extras,
    )
    from app.services.flow_executor import FlowExecutor

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

        max_sends = max(1, int(extras.get("follow_up_send_count") or 1))
        frequency = str(extras.get("follow_up_frequency") or "once_per_dialogue")
        off_hours_mode = str(
            extras.get("follow_up_off_hours_mode") or "defer_next_window"
        )
        delay_s = follow_up_delay_seconds(extras)

        schedule_cfg = (
            bot.schedule_config if isinstance(bot.schedule_config, dict) else {}
        )
        schedule_ok = FlowExecutor()._is_within_schedule(
            {
                "schedule_config": schedule_cfg,
                "timezone": bot.timezone,
            }
        )
        if not schedule_ok:
            if off_hours_mode == "skip":
                cancel_follow_up_message(bot_id=bot_id, chat_id=chat_id)
                return {"status": "skipped", "reason": "off_schedule_skip"}
            if off_hours_mode == "send_anyway":
                pass
            else:
                wait_s = seconds_until_next_schedule_window(
                    schedule_cfg, timezone_name=bot.timezone
                )
                countdown = wait_s if wait_s and wait_s > 0 else 3600
                async_result = send_follow_up_message.apply_async(
                    kwargs={
                        "bot_id": bot_id,
                        "chat_id": chat_id,
                        "client_id": client_id,
                        "scheduled_at": scheduled_at,
                        "sent_count": sent_count,
                        "channel": channel,
                    },
                    countdown=countdown,
                )
                _store_task_id(
                    bot_id, chat_id, async_result.id, ttl_seconds=countdown
                )
                return {
                    "status": "deferred",
                    "reason": "off_schedule",
                    "countdown": str(countdown),
                }

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
            sender = str(getattr(latest.sender, "value", latest.sender)).upper()
            if sender == "CLIENT" and latest_at > scheduled_dt:
                cancel_follow_up_message(bot_id=bot_id, chat_id=chat_id)
                return {"status": "skipped", "reason": "user_replied"}

        text = await _compose_follow_up_text(
            bot=bot,
            client_id=uuid.UUID(client_id),
            db=db,
            instructions=str(extras.get("follow_up_instructions") or ""),
        )

        try:
            await _deliver_channel_text(
                db,
                bot=bot,
                channel=channel,
                chat_id=chat_id,
                client_id=uuid.UUID(client_id),
                text=text,
            )
        except Exception as exc:
            logger.warning(
                "FollowUp.deliver_failed | bot_id={bot_id} channel={channel} error={error}",
                bot_id=bot_id,
                channel=channel,
                error=str(exc),
            )
            return {"status": "skipped", "reason": "deliver_failed"}

        await _persist_follow_up_message(
            db, client_id=uuid.UUID(client_id), text=text
        )
        await db.commit()

    next_sent = int(sent_count) + 1
    if next_sent < max_sends:
        schedule_follow_up_message(
            bot_id=bot_id,
            chat_id=chat_id,
            client_id=client_id,
            delay_seconds=delay_s,
            sent_count=next_sent,
            force=True,
            channel=channel,
        )
        _save_state(
            bot_id,
            chat_id,
            sent_count=next_sent,
            chain_done=False,
            ttl_seconds=delay_s + 7 * 86400,
        )
    else:
        chain_done = frequency == "once_per_dialogue"
        _save_state(
            bot_id,
            chat_id,
            sent_count=next_sent,
            chain_done=chain_done,
            ttl_seconds=7 * 86400,
        )
        try:
            _get_redis().delete(_redis_key(bot_id, chat_id))
        except Exception:
            pass

    logger.info(
        "FollowUp.sent | bot_id={bot_id} chat_id={chat_id} n={n}/{max_n}",
        bot_id=bot_id,
        chat_id=chat_id,
        n=next_sent,
        max_n=max_sends,
    )
    return {"status": "sent", "sent_count": str(next_sent)}
