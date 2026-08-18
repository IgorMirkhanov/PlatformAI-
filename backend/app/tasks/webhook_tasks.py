from __future__ import annotations

import asyncio
from typing import Any

from celery.exceptions import MaxRetriesExceededError
from loguru import logger

from app.config import settings
from app.core.celery_app import celery_app
from app.core.database import async_session_factory
from app.models.core_models import ChatMessage, Client, MessageSender
from app.services.chat_service import broadcast_chat_message
from app.services.messenger_errors import MessengerAPIError
from app.services.telegram_service import telegram_service
from app.workers.webhook_workers import process_inbound_message_worker


async def _execute_inbound_message(
    bot_id: str,
    platform_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Delegate to the production webhook worker (AI + RAG + outbound dispatch)."""
    return await process_inbound_message_worker(bot_id, platform_type, payload)


async def _notify_operator_dead_letter(
    *,
    bot_id: str,
    platform_type: str,
    payload: dict[str, Any],
    error_message: str,
) -> None:
    import uuid

    from sqlalchemy import select

    external_id = str(payload.get("external_id") or payload.get("chat_id") or "unknown")
    bot_uuid: uuid.UUID | None = None

    try:
        bot_uuid = uuid.UUID(bot_id) if bot_id else None
    except ValueError:
        bot_uuid = None

    if bot_uuid is None and platform_type.upper() == "TELEGRAM":
        async with async_session_factory() as lookup_db:
            bot = await telegram_service.get_bot_by_token_hash(
                lookup_db,
                str(payload.get("bot_token_hash") or ""),
            )
            bot_uuid = bot.id if bot else None

    if bot_uuid is None:
        logger.error(
            "CeleryWorker.dlq_skipped | reason=bot_unresolved bot_id={bot_id} platform={platform}",
            bot_id=bot_id,
            platform=platform_type,
        )
        return

    async with async_session_factory() as db:
        try:
            client_result = await db.execute(
                select(Client).where(
                    Client.bot_id == bot_uuid,
                    Client.external_id == external_id,
                )
            )
            client = client_result.scalar_one_or_none()
            if client is None:
                client = Client(
                    bot_id=bot_uuid,
                    external_id=external_id,
                    username=str(payload.get("username") or external_id),
                    first_name=str(payload.get("first_name") or external_id),
                )
                db.add(client)
                await db.flush()

            alert = ChatMessage(
                client_id=client.id,
                sender=MessageSender.OPERATOR,
                message_text=(
                    "[System] Inbound message processing failed after retries. "
                    f"Platform={platform_type}. Error: {error_message[:500]}"
                ),
                payload={
                    "source": "celery_dead_letter",
                    "platform_type": platform_type,
                    "original_payload_preview": str(payload)[:1000],
                    "error": error_message[:1000],
                },
            )
            db.add(alert)
            await db.flush()
            await broadcast_chat_message(client, alert)
            await db.commit()
            logger.warning(
                "CeleryWorker.dlq_notified | bot_id={bot_id} client_id={client_id} platform={platform}",
                bot_id=bot_uuid,
                client_id=client.id,
                platform=platform_type,
            )
        except Exception as exc:
            await db.rollback()
            logger.exception(
                "CeleryWorker.dlq_notify_failed | bot_id={bot_id} error={error}",
                bot_id=bot_uuid,
                error=str(exc),
            )


@celery_app.task(
    bind=True,
    name="app.tasks.webhook_tasks.process_inbound_message_task",
    max_retries=settings.CELERY_INBOUND_MAX_RETRIES,
)
def process_inbound_message_task(
    self,
    bot_id: str,
    platform_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Process an inbound messenger webhook asynchronously on dedicated workers."""
    logger.info(
        "CeleryWorker.inbound_task_received | task_id={task_id} bot_id={bot_id} platform={platform} retries={retries}",
        task_id=self.request.id,
        bot_id=bot_id or "resolved_in_worker",
        platform=platform_type,
        retries=self.request.retries,
    )

    try:
        result = asyncio.run(_execute_inbound_message(bot_id, platform_type, payload))
        logger.info(
            "CeleryWorker.inbound_task_complete | task_id={task_id} bot_id={bot_id} platform={platform}",
            task_id=self.request.id,
            bot_id=bot_id or "resolved_in_worker",
            platform=platform_type,
        )
        return result
    except MessengerAPIError as exc:
        logger.error(
            "CeleryWorker.messenger_api_error | task_id={task_id} bot_id={bot_id} "
            "platform={platform} status={status} retriable={retriable}",
            task_id=self.request.id,
            bot_id=bot_id or "resolved_in_worker",
            platform=platform_type,
            status=exc.status_code,
            retriable=exc.retriable,
        )
        if not exc.retriable:
            return {
                "status": "failed",
                "reason": "messenger_api_error",
                "channel": exc.channel,
                "status_code": exc.status_code,
                "detail": exc.detail[:500],
            }
        try:
            countdown = settings.CELERY_INBOUND_RETRY_BACKOFF * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            asyncio.run(
                _notify_operator_dead_letter(
                    bot_id=bot_id,
                    platform_type=platform_type,
                    payload=payload,
                    error_message=str(exc),
                )
            )
            raise
    except Exception as exc:
        logger.exception(
            "CeleryWorker.inbound_task_failed | task_id={task_id} bot_id={bot_id} platform={platform} error={error} retry={retry}",
            task_id=self.request.id,
            bot_id=bot_id or "resolved_in_worker",
            platform=platform_type,
            error=str(exc),
            retry=self.request.retries,
        )
        try:
            countdown = settings.CELERY_INBOUND_RETRY_BACKOFF * (2 ** self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            asyncio.run(
                _notify_operator_dead_letter(
                    bot_id=bot_id,
                    platform_type=platform_type,
                    payload=payload,
                    error_message=str(exc),
                )
            )
            raise
