"""Wazzup MessagingAdapter Celery — inbound message.received events."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import async_session_factory, run_celery_async
from app.models.integration_hub import IntegrationConnection
from app.services.inbound.normalizer import attach_normalized, normalize_telegram, normalize_whatsapp
from app.services.integration_hub.hub_usage import record_hub_usage
from app.tasks.webhook_tasks import process_inbound_message_task


@celery_app.task(
    bind=True,
    name="app.tasks.wazzup_tasks.process_wazzup_event_task",
    max_retries=6,
    acks_late=True,
)
def process_wazzup_event_task(
    self,
    connection_id: str,
    events: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    _ = payload
    return run_celery_async(_process(connection_id, events))


async def _process(connection_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    async with async_session_factory() as db:
        connection = await db.get(IntegrationConnection, UUID(connection_id))
        if connection is None:
            return {"status": "missing"}
        await record_hub_usage(
            db,
            connection=connection,
            metric="wazzup_webhook",
            quantity=max(1, len(events)),
        )
        await db.commit()
        bot_id = connection.bot_id
    inbound = 0
    for event in events:
        if event.get("is_echo") or not event.get("text"):
            continue
        if bot_id is None:
            continue
        kind = str(event.get("channel_type") or "whatsapp").lower()
        chat_id = str(event.get("chat_id") or "")
        text = str(event.get("text") or "")
        name = ""
        from_block = event.get("from")
        if isinstance(from_block, dict):
            name = str(from_block.get("name") or "")
        if kind == "telegram":
            normalized = normalize_telegram(
                bot_id=bot_id,
                chat_id=chat_id,
                message_text=text,
                first_name=name or None,
            )
        else:
            normalized = normalize_whatsapp(
                bot_id=bot_id,
                phone=chat_id,
                message_text=text,
                client_name=name or chat_id,
                provider="wazzup",
            )
        normalized.metadata["channel_id"] = str(event.get("channel_id") or "")
        normalized.metadata["hub_channel_type"] = "wazzup"
        task_payload = attach_normalized(
            {
                "bot_id": str(bot_id),
                "body": event,
                "external_id": chat_id,
                "message_text": text,
                "channel_id": event.get("channel_id"),
                "hub_connection_id": connection_id,
            },
            normalized,
        )
        process_inbound_message_task.apply_async(
            args=[str(bot_id), "WAZZUP", task_payload],
            queue=settings.CELERY_INBOUND_QUEUE,
        )
        inbound += 1
    logger.info(
        "Wazzup.event_processed | connection_id={id} events={n} inbound={inbound}",
        id=connection_id,
        n=len(events),
        inbound=inbound,
    )
    return {"status": "ok", "events": len(events), "inbound": inbound}
