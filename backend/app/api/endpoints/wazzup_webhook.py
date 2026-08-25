"""Wazzup inbound webhook router — resolve bot by ``channelId`` (Multi-Wazzup)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.schemas.core_schemas import WebhookQueuedResponse
from app.tasks.webhook_tasks import process_inbound_message_task

router = APIRouter(tags=["webhooks"])


def _enqueue_inbound_message(
    *,
    bot_id: str,
    platform_type: str,
    payload: dict[str, Any],
    normalized: dict[str, Any] | None = None,
) -> WebhookQueuedResponse:
    task_payload = dict(payload)
    if normalized is not None:
        task_payload["normalized"] = normalized
    task = process_inbound_message_task.apply_async(
        args=[bot_id, platform_type, task_payload],
        queue=settings.CELERY_INBOUND_QUEUE,
    )
    logger.info(
        "WebhookEndpoint.queued | task_id={task_id} bot_id={bot_id} platform={platform} queue={queue}",
        task_id=task.id,
        bot_id=bot_id or "resolved_in_worker",
        platform=platform_type,
        queue=settings.CELERY_INBOUND_QUEUE,
    )
    return WebhookQueuedResponse(status="queued", task_id=task.id)


async def _handle_wazzup_payload(
    *,
    request: Request,
    db: AsyncSession,
    raw_body: dict[str, Any],
    path_bot_id: uuid.UUID | None = None,
) -> WebhookQueuedResponse | Response:
    from app.core.redis_client import claim_inbound_event
    from app.core.webhook_auth import require_internal_service_key
    from app.models.channels import HubChannelStatus
    from app.services.inbound.normalizer import attach_normalized, normalize_wazzup_inbound
    from app.services.wazzup_service import wazzup_service

    try:
        require_internal_service_key(request)
    except HTTPException:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    event_id = str(
        raw_body.get("messageId")
        or raw_body.get("message_id")
        or raw_body.get("id")
        or ""
    ) or None
    if event_id and not claim_inbound_event("wazzup", event_id):
        return Response(status_code=status.HTTP_200_OK)

    inbound_items = wazzup_service.extract_inbound_messages(raw_body)
    channel_id = (
        (inbound_items[0].get("channel_id") if inbound_items else None)
        or wazzup_service.extract_channel_id(raw_body)
        or ""
    ).strip()

    channel = None
    if channel_id:
        channel = await wazzup_service.get_channel_by_reference_id(db, channel_id)

    if channel is None:
        if path_bot_id is not None:
            # Legacy bot-scoped URL — fall back to connected channel for that bot.
            channel = await wazzup_service.get_channel(db, path_bot_id, channel_id=channel_id or None)
        if channel is None:
            logger.warning(
                "[WAZZUP] Unregistered channelId: {channelId}",
                channelId=channel_id or "<missing>",
            )
            return Response(status_code=status.HTTP_200_OK)

    if channel.status != HubChannelStatus.CONNECTED:
        logger.warning(
            "[WAZZUP] Unregistered channelId: {channelId}",
            channelId=channel.reference_id or channel_id or "<missing>",
        )
        return Response(status_code=status.HTTP_200_OK)

    bot_id = channel.bot_id
    org_id = getattr(getattr(channel, "bot", None), "organization_id", None)

    first = inbound_items[0] if inbound_items else None
    base_payload: dict[str, Any] = {
        "bot_id": str(bot_id),
        "organization_id": str(org_id) if org_id else None,
        "bot_channel_id": str(channel.id),
        "body": raw_body,
        "external_id": first["external_id"] if first else None,
        "username": first["username"] if first else None,
        "first_name": first["first_name"] if first else None,
        "message_text": first["message_text"] if first else None,
        "channel_id": channel.reference_id or channel_id,
    }
    if first:
        normalized = normalize_wazzup_inbound(
            bot_id=bot_id,
            inbound=first,
            raw_body=raw_body,
        )
        payload = attach_normalized(base_payload, normalized)
    else:
        payload = base_payload

    return _enqueue_inbound_message(
        bot_id=str(bot_id),
        platform_type="WAZZUP",
        payload=payload,
        normalized=payload.get("normalized"),
    )


@router.post(
    "/webhooks/wazzup",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive Wazzup24 webhooks (route by channelId)",
)
async def wazzup_webhook_routed(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    """Shared Wazzup webhook — resolves ``bot_id`` from ``channelId`` → ``BotChannel.reference_id``."""
    try:
        raw_body: Any = await request.json()
        if not isinstance(raw_body, dict):
            return Response(status_code=status.HTTP_200_OK)
        return await _handle_wazzup_payload(
            request=request,
            db=db,
            raw_body=raw_body,
            path_bot_id=None,
        )
    except Exception as exc:
        logger.exception(
            "WebhookEndpoint.wazzup_routed_unhandled | error={error}",
            error=str(exc),
        )
        return Response(status_code=status.HTTP_200_OK)


@router.post(
    "/webhooks/wazzup/{bot_id}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive Wazzup24 webhooks (legacy bot-scoped URL)",
)
async def wazzup_webhook(
    bot_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    """Legacy path — still routes by ``channelId`` when present; ``bot_id`` is a fallback hint."""
    try:
        raw_body: Any = await request.json()
        if not isinstance(raw_body, dict):
            return Response(status_code=status.HTTP_200_OK)
        return await _handle_wazzup_payload(
            request=request,
            db=db,
            raw_body=raw_body,
            path_bot_id=bot_id,
        )
    except Exception as exc:
        logger.exception(
            "WebhookEndpoint.wazzup_unhandled | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        return Response(status_code=status.HTTP_200_OK)
