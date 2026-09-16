"""Green API receiveNotification poller — used when webhookUrl cannot reach localhost."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy import select
from starlette.requests import Request

from app.config import settings
from app.core.celery_app import celery_app
from app.core.database import async_session_factory, run_celery_async
from app.core.redis_client import get_redis_client
from app.core.security import decrypt_credential
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.services.greenapi_service import greenapi_service
from app.services.webhooks.router_service import ingest_provider_webhook

POLL_LOCK_KEY = "greenapi:poll:lock"
POLL_LOCK_TTL = 25
POLL_INTERVAL_SECONDS = 4
_GREEN_TYPES = (
    HubChannelType.GREENAPI,
    HubChannelType.WHATSAPP_QR,
    HubChannelType.INSTAGRAM,
)


def _is_polling_row(row: BotChannel) -> bool:
    meta = row.meta_data if isinstance(row.meta_data, dict) else {}
    if str(meta.get("provider") or "").lower() != "greenapi":
        return False
    mode = str(meta.get("delivery_mode") or "").strip().lower()
    if mode == "webhook":
        return False
    return bool(row.encrypted_token and row.reference_id)


def _dummy_request() -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/webhooks/greenapi",
            "raw_path": b"/api/v1/webhooks/greenapi",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 0),
            "server": ("127.0.0.1", 8000),
        }
    )


async def _poll_connected_instances() -> int:
    processed = 0
    async with async_session_factory() as db:
        rows = list(
            (
                await db.scalars(
                    select(BotChannel).where(
                        BotChannel.channel_type.in_(_GREEN_TYPES),
                        BotChannel.status == HubChannelStatus.CONNECTED,
                    )
                )
            ).all()
        )
        seen: set[str] = set()
        for row in rows:
            if not _is_polling_row(row):
                continue
            instance = str(row.reference_id or "").strip()
            try:
                token = decrypt_credential(row.encrypted_token or "")
            except Exception as exc:
                logger.warning(
                    "GreenApiPoll.decrypt_failed | bot_id={bot_id} error={error}",
                    bot_id=row.bot_id,
                    error=str(exc),
                )
                continue
            key = f"{instance}:{token[:8]}"
            if not instance or not token or key in seen:
                continue
            seen.add(key)
            for _ in range(8):
                notice = await greenapi_service.receive_notification(instance, token)
                if not notice:
                    break
                receipt_id = notice.get("receiptId")
                body = notice.get("body") if isinstance(notice.get("body"), dict) else notice
                if isinstance(body, dict):
                    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                    try:
                        await ingest_provider_webhook(
                            provider="greenapi",
                            request=_dummy_request(),
                            db=db,
                            raw_bytes=raw,
                        )
                        processed += 1
                    except Exception as exc:
                        logger.warning(
                            "GreenApiPoll.ingest_failed | instance={instance} error={error}",
                            instance=instance,
                            error=str(exc),
                        )
                if receipt_id is not None:
                    try:
                        await greenapi_service.delete_notification(instance, token, int(receipt_id))
                    except Exception:
                        logger.warning(
                            "GreenApiPoll.delete_failed | instance={instance} receipt={receipt}",
                            instance=instance,
                            receipt=receipt_id,
                        )
    return processed


@celery_app.task(name="app.tasks.greenapi_poll_task.poll_greenapi_notifications")
def poll_greenapi_notifications() -> dict[str, Any]:
    redis = get_redis_client()
    acquired = bool(redis.set(POLL_LOCK_KEY, "1", nx=True, ex=POLL_LOCK_TTL))
    processed = 0
    try:
        if acquired:
            redis.set("greenapi:poller:armed", "1", ex=60)
            processed = run_celery_async(_poll_connected_instances())
    except Exception as exc:
        logger.exception("GreenApiPoll.failed | error={error}", error=str(exc))
    finally:
        if acquired:
            try:
                redis.delete(POLL_LOCK_KEY)
            except Exception:
                pass
            if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
                poll_greenapi_notifications.apply_async(countdown=POLL_INTERVAL_SECONDS)
    return {"processed": processed}
