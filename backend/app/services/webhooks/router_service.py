"""Shared inbound webhook pipeline: parse → resolve → verify → dedup → enqueue."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from typing import Any

from fastapi import HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.metrics import record_webhook_event
from app.core.redis_client import claim_inbound_event
from app.core.webhook_auth import verify_telegram_secret_token_detailed
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.models.tenant_credentials import WebhookEventLog
from app.schemas.core_schemas import WebhookQueuedResponse
from app.services.webhooks.parsers import ParsedInbound, parse_inbound
from app.tasks.webhook_tasks import process_inbound_message_task

_PROVIDER_TO_HUB: dict[str, HubChannelType] = {
    "telegram": HubChannelType.TELEGRAM,
    "wazzup": HubChannelType.WAZZUP,
    "greenapi": HubChannelType.GREENAPI,
    "widget": HubChannelType.WEB_WIDGET,
    "web_widget": HubChannelType.WEB_WIDGET,
}

_GREENAPI_LOOKUP_TYPES: tuple[HubChannelType, ...] = (
    HubChannelType.GREENAPI,
    HubChannelType.WHATSAPP_QR,
    HubChannelType.INSTAGRAM,
)

_PROVIDER_TO_PLATFORM: dict[str, str] = {
    "telegram": "TELEGRAM",
    "wazzup": "WAZZUP",
    "greenapi": "WHATSAPP",
    "widget": "WEB_WIDGET",
    "web_widget": "WEB_WIDGET",
}


def verify_hmac_signature(raw_body: bytes, header: str | None, secret: str | None) -> bool:
    expected_secret = (secret or "").strip()
    if not expected_secret:
        return not settings.is_production
    provided = (header or "").strip()
    if provided.lower().startswith("sha256="):
        provided = provided.split("=", 1)[1].strip()
    digest = hmac.new(expected_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return bool(provided) and secrets.compare_digest(digest, provided)


async def _persist_event_log(
    db: AsyncSession,
    *,
    provider: str,
    reference_id: str,
    external_message_id: str,
    payload_hash: str,
    unmatched: bool = False,
) -> bool:
    """Return True if this is the first insert (not a duplicate)."""
    stmt = (
        pg_insert(WebhookEventLog)
        .values(
            id=uuid.uuid4(),
            provider=provider,
            reference_id=reference_id,
            external_message_id=external_message_id,
            payload_hash=payload_hash,
            unmatched=unmatched,
        )
        .on_conflict_do_nothing(
            constraint="uq_webhook_event_log_provider_ref_msg",
        )
        .returning(WebhookEventLog.id)
    )
    inserted = await db.scalar(stmt)
    return inserted is not None


async def resolve_channel(
    db: AsyncSession,
    *,
    provider: str,
    reference_id: str,
) -> BotChannel | None:
    hub = _PROVIDER_TO_HUB.get(provider)
    if not reference_id:
        return None
    if provider == "greenapi":
        stmt = select(BotChannel).where(
            BotChannel.channel_type.in_(_GREENAPI_LOOKUP_TYPES),
            BotChannel.reference_id == reference_id,
            BotChannel.status == HubChannelStatus.CONNECTED,
        )
        return await db.scalar(stmt)
    if hub is None:
        return None
    stmt = select(BotChannel).where(
        BotChannel.channel_type == hub,
        BotChannel.reference_id == reference_id,
        BotChannel.status == HubChannelStatus.CONNECTED,
    )
    channel = await db.scalar(stmt)
    if channel is not None:
        return channel
    # Telegram: also match token hash stored as reference_id regardless of status.
    stmt = select(BotChannel).where(
        BotChannel.channel_type == hub,
        BotChannel.reference_id == reference_id,
    )
    return await db.scalar(stmt)


async def ingest_provider_webhook(
    *,
    provider: str,
    request: Request,
    db: AsyncSession,
    raw_bytes: bytes,
    overlay_reference_id: str | None = None,
) -> WebhookQueuedResponse | Response:
    provider_key = (provider or "").strip().lower()
    payload_hash = hashlib.sha256(raw_bytes).hexdigest()
    try:
        payload = json.loads(raw_bytes.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        record_webhook_event(provider_key, "invalid")
        return Response(status_code=status.HTTP_200_OK)
    if not isinstance(payload, dict):
        record_webhook_event(provider_key, "invalid")
        return Response(status_code=status.HTTP_200_OK)

    parsed = parse_inbound(provider_key, payload)
    if parsed is None:
        record_webhook_event(provider_key, "unparsed")
        return Response(status_code=status.HTTP_200_OK)

    reference_id = (overlay_reference_id or parsed.reference_id).strip()
    channel = await resolve_channel(db, provider=provider_key, reference_id=reference_id)
    if channel is None:
        await _persist_event_log(
            db,
            provider=provider_key,
            reference_id=reference_id or "unknown",
            external_message_id=parsed.external_message_id,
            payload_hash=payload_hash,
            unmatched=True,
        )
        await db.commit()
        record_webhook_event(provider_key, "unmatched")
        logger.warning(
            "WebhookRouter.unmatched | provider={provider} reference_id={ref}",
            provider=provider_key,
            ref=reference_id[:64],
        )
        return Response(status_code=status.HTTP_200_OK)

    secret = (channel.webhook_secret or "").strip() or str(
        (channel.meta_data or {}).get("webhook_secret_token") or ""
    )
    if provider_key == "telegram":
        header_secret = request.headers.get("x-telegram-bot-api-secret-token")
        ok, reason = verify_telegram_secret_token_detailed(header_secret, secret)
        if not ok:
            logger.error("WebhookRouter.telegram_forbidden | reason={reason}", reason=reason)
            record_webhook_event(provider_key, "forbidden")
            return Response(status_code=status.HTTP_403_FORBIDDEN)
    else:
        hmac_header = (
            request.headers.get("x-signature")
            or request.headers.get("x-hub-signature-256")
            or request.headers.get("x-webhook-signature")
        )
        if secret and hmac_header and not verify_hmac_signature(raw_bytes, hmac_header, secret):
            record_webhook_event(provider_key, "forbidden")
            return Response(status_code=status.HTTP_403_FORBIDDEN)

    lock_ok = claim_inbound_event(
        provider_key,
        f"{reference_id}:{parsed.external_message_id}",
        ttl_seconds=30,
    )
    if not lock_ok:
        record_webhook_event(provider_key, "duplicate")
        return Response(status_code=status.HTTP_200_OK)

    first = await _persist_event_log(
        db,
        provider=provider_key,
        reference_id=reference_id,
        external_message_id=parsed.external_message_id,
        payload_hash=payload_hash,
    )
    await db.commit()
    if not first:
        record_webhook_event(provider_key, "duplicate")
        return Response(status_code=status.HTTP_200_OK)

    platform = _PROVIDER_TO_PLATFORM.get(provider_key, provider_key.upper())
    task = process_inbound_message_task.apply_async(
        args=[str(channel.bot_id), platform, dict(payload)],
        queue=settings.CELERY_INBOUND_QUEUE,
    )
    record_webhook_event(provider_key, "queued")
    logger.info(
        "WebhookRouter.queued | provider={provider} bot_id={bot_id} task_id={task_id} "
        "conversation_ref={chat}",
        provider=provider_key,
        bot_id=channel.bot_id,
        task_id=task.id,
        chat=parsed.external_chat_id,
    )
    return WebhookQueuedResponse(status="queued", task_id=task.id)
