"""Local Telegram getUpdates poller — used when setWebhook cannot reach localhost."""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select

from app.config import settings
from app.core.celery_app import celery_app
from app.core.database import async_session_factory, run_celery_async
from app.core.redis_client import claim_telegram_inbound, get_redis_client
from app.core.security import decrypt_credential
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.schemas.webhook_schemas import TelegramUpdate
from app.services.telegram_service import telegram_service
from app.tasks.webhook_tasks import process_inbound_message_task

POLL_LOCK_KEY = "telegram:poll:lock"
# Must cover long-poll getUpdates (25s) + processing slack.
POLL_LOCK_TTL = 45
OFFSET_KEY = "telegram:poll:offset:{token_hash}"
POLL_INTERVAL_SECONDS = 1
# Hold Telegram's getUpdates stream so a competing poller cannot steal updates.
TELEGRAM_LONG_POLL_TIMEOUT = 25


def _is_polling_row(row: BotChannel) -> bool:
    meta = row.meta_data if isinstance(row.meta_data, dict) else {}
    mode = str(meta.get("delivery_mode") or "").strip().lower()
    if mode == "webhook":
        return False
    if mode == "polling":
        return True
    webhook_url = str(meta.get("webhook_url") or "")
    return telegram_service.telegram_delivery_mode(webhook_url) == "polling"


def _extract_message_id(raw: dict[str, Any]) -> str | None:
    for key in ("message", "edited_message", "business_message", "edited_business_message"):
        block = raw.get(key)
        if isinstance(block, dict) and block.get("message_id") is not None:
            return str(block.get("message_id"))
    callback = raw.get("callback_query")
    if isinstance(callback, dict):
        msg = callback.get("message")
        if isinstance(msg, dict) and msg.get("message_id") is not None:
            return str(msg.get("message_id"))
    return None


async def _switch_unreachable_channels() -> None:
    """Move webhook channels to getUpdates when Telegram cannot deliver.

    Pending updates are kept (deleteWebhook does not drop them) and the same
    poll cycle then reads them.
    """
    from sqlalchemy.orm.attributes import flag_modified

    from app.services.telegram_delivery import (
        error_means_unreachable,
        note_webhook_failure,
        webhook_delivery_blocked,
    )

    async with async_session_factory() as db:
        result = await db.execute(
            select(BotChannel).where(
                BotChannel.channel_type.in_(
                    (HubChannelType.TELEGRAM, HubChannelType.TELEGRAM_BUSINESS)
                ),
                BotChannel.status == HubChannelStatus.CONNECTED,
                BotChannel.encrypted_token.is_not(None),
            )
        )
        rows = list(result.scalars().all())
        changed = False
        for row in rows:
            meta = dict(row.meta_data) if isinstance(row.meta_data, dict) else {}
            if str(meta.get("delivery_mode") or "").strip().lower() == "polling":
                continue
            try:
                token = decrypt_credential(row.encrypted_token or "")
            except Exception:
                continue
            if not token:
                continue
            info = await telegram_service.get_webhook_info(token)
            last_error = str(info.get("last_error_message") or "")
            if error_means_unreachable(last_error):
                note_webhook_failure(last_error)
            if not webhook_delivery_blocked() and not error_means_unreachable(last_error):
                continue
            try:
                await telegram_service.delete_webhook(token)
            except Exception as exc:
                logger.warning(
                    "TelegramPoll.delete_webhook_failed | bot_id={bot_id} error={error}",
                    bot_id=row.bot_id,
                    error=type(exc).__name__,
                )
            meta["delivery_mode"] = "polling"
            row.meta_data = meta
            flag_modified(row, "meta_data")
            changed = True
            logger.info(
                "TelegramPoll.switched_to_polling | bot_id={bot_id}",
                bot_id=row.bot_id,
            )
        if changed:
            await db.commit()


async def _poll_connected_bots() -> int:
    await _switch_unreachable_channels()
    processed = 0
    redis = get_redis_client()
    async with async_session_factory() as db:
        result = await db.execute(
            select(BotChannel).where(
                BotChannel.channel_type.in_(
                    (HubChannelType.TELEGRAM, HubChannelType.TELEGRAM_BUSINESS)
                ),
                BotChannel.status == HubChannelStatus.CONNECTED,
                BotChannel.encrypted_token.is_not(None),
            )
        )
        rows = list(result.scalars().all())

    # One getUpdates stream per bot token (avoid TELEGRAM + BUSINESS dual poll).
    seen_tokens: set[str] = set()

    for row in rows:
        if not _is_polling_row(row):
            continue
        token = ""
        try:
            token = decrypt_credential(row.encrypted_token or "")
        except Exception as exc:
            logger.warning(
                "TelegramPoll.decrypt_failed | bot_id={bot_id} error={error}",
                bot_id=row.bot_id,
                error=str(exc),
            )
            continue
        if not token or token in seen_tokens:
            continue
        seen_tokens.add(token)

        meta = row.meta_data if isinstance(row.meta_data, dict) else {}
        token_hash = str(meta.get("token_hash") or row.bot_id)
        offset_raw = redis.get(OFFSET_KEY.format(token_hash=token_hash))
        offset = int(offset_raw) if offset_raw else None
        updates = await telegram_service.fetch_updates(
            token,
            offset=offset,
            timeout=TELEGRAM_LONG_POLL_TIMEOUT,
        )
        if not updates:
            continue

        max_update_id: int | None = None
        for raw in updates:
            if not isinstance(raw, dict):
                continue
            update_id = raw.get("update_id")
            if update_id is not None:
                try:
                    uid = int(update_id)
                    max_update_id = uid if max_update_id is None else max(max_update_id, uid)
                except (TypeError, ValueError):
                    uid = None
            else:
                uid = None

            try:
                update = TelegramUpdate.model_validate(raw)
            except Exception:
                continue
            parsed = telegram_service.extract_inbound_fields(update)
            message_id = _extract_message_id(raw)
            chat_id = parsed.chat_id if parsed else None
            if not claim_telegram_inbound(
                update_id=uid if uid is not None else update_id,
                bot_id=str(row.bot_id),
                chat_id=chat_id,
                message_id=message_id,
                message_text=parsed.message_text if parsed else None,
            ):
                logger.info(
                    "TelegramPoll.dedup_skip | bot_id={bot_id} update_id={update_id} message_id={message_id}",
                    bot_id=row.bot_id,
                    update_id=update_id,
                    message_id=message_id,
                )
                continue

            process_inbound_message_task.apply_async(
                args=[
                    str(row.bot_id),
                    "TELEGRAM",
                    {
                        "bot_id": str(row.bot_id),
                        "bot_token_hash": token_hash,
                        "update": update.to_raw_dict() if parsed else raw,
                        "external_id": parsed.chat_id if parsed else None,
                        "username": parsed.username if parsed else None,
                        "first_name": parsed.first_name if parsed else None,
                        "last_name": parsed.last_name if parsed else None,
                        "message_text": parsed.message_text if parsed else None,
                        "telegram_message_id": message_id,
                    },
                ],
                queue=settings.CELERY_INBOUND_QUEUE,
            )
            processed += 1

        # Confirm offsets with Telegram immediately so the next poll cannot redeliver.
        if max_update_id is not None:
            next_offset = max_update_id + 1
            redis.set(OFFSET_KEY.format(token_hash=token_hash), next_offset)
            await telegram_service.fetch_updates(token, offset=next_offset, timeout=0)

    return processed


@celery_app.task(name="app.tasks.telegram_poll_task.poll_telegram_updates")
def poll_telegram_updates() -> dict[str, Any]:
    redis = get_redis_client()
    acquired = bool(redis.set(POLL_LOCK_KEY, "1", nx=True, ex=POLL_LOCK_TTL))
    processed = 0
    try:
        if acquired:
            redis.set("telegram:poller:armed", "1", ex=60)
            processed = run_celery_async(_poll_connected_bots())
    except Exception as exc:
        logger.exception("TelegramPoll.failed | error={error}", error=str(exc))
    finally:
        if acquired:
            try:
                redis.delete(POLL_LOCK_KEY)
            except Exception:
                pass
            if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
                poll_telegram_updates.apply_async(countdown=POLL_INTERVAL_SECONDS)
    return {"processed": processed}
