"""Telegram Bot API Omnichannel webhook endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, rate_limit_key_org
from app.core.security import hash_bot_token
from app.services.omnichannel.base_connector import ChannelConnectorError
from app.services.omnichannel.connectors.telegram_connector import TelegramConnector
from app.services.omnichannel.message_log_service import message_log_service

router = APIRouter(prefix="/omnichannel/telegram", tags=["omnichannel-telegram"])


class TelegramWebhookResult(BaseModel):
    status: str = "ok"
    logged: int = 0
    queued: int = 0
    message_ids: list[str] = Field(default_factory=list)
    ignored: bool = False
    reason: str | None = None


def _resolve_bot_token(bot_token_hash: str) -> str | None:
    """
    Resolve bot token for this webhook route.

    When ``TELEGRAM_DEFAULT_BOT_TOKEN`` is set, the path hash must match its
    SHA-256 digest (stable URL routing without exposing the raw token).
    """
    token = getattr(settings, "TELEGRAM_DEFAULT_BOT_TOKEN", None)
    if not token:
        # Multi-tenant token lookup is deferred; parse-only path still works.
        return None
    expected = hash_bot_token(str(token))
    incoming = bot_token_hash.strip().lower()
    if incoming != expected.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Telegram webhook token hash mismatch.",
        )
    return str(token)


@router.post(
    "/webhook/{bot_token_hash}",
    response_model=TelegramWebhookResult,
    summary="Receive Telegram Bot API Updates",
)
@limiter.limit("60/minute", key_func=rate_limit_key_org)
async def telegram_receive_webhook(
    bot_token_hash: str,
    request: Request,
    organization_id: uuid.UUID = Query(
        ...,
        description="Tenant that owns this Telegram bot binding.",
    ),
    db: AsyncSession = Depends(get_db),
) -> TelegramWebhookResult:
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON webhook body.",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body must be a JSON object.",
        )

    bot_token = _resolve_bot_token(bot_token_hash)
    # Token is optional for parse-only; required later for outbound replies.
    connector = TelegramConnector(
        organization_id=organization_id,
        bot_token=bot_token,
    )

    try:
        inbound_messages = connector.parse_all_inbound(payload)
    except ChannelConnectorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not inbound_messages:
        logger.debug(
            "Omnichannel.Telegram.ignored_update | org={org} hash={hash}",
            org=organization_id,
            hash=bot_token_hash[:12],
        )
        return TelegramWebhookResult(
            status="ok",
            logged=0,
            queued=0,
            ignored=True,
            reason="unsupported_or_empty_update",
        )

    from app.services.inbound.omnichannel_bridge import (
        enqueue_omnichannel_inbound,
        resolve_bot_for_omnichannel,
    )

    bot = await resolve_bot_for_omnichannel(
        db,
        organization_id=organization_id,
        channel="telegram",
    )
    if bot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active Telegram bot found for this organization.",
        )

    logged_ids: list[str] = []
    queued_count = 0
    for inbound in inbound_messages:
        try:
            await message_log_service.log_inbound(db, inbound)
            logged_ids.append(inbound.channel_message_id)
        except Exception as exc:
            logger.exception(
                "Omnichannel.Telegram.log_failed | org={org} mid={mid} error={error}",
                org=organization_id,
                mid=inbound.channel_message_id,
                error=str(exc),
            )
        task_id = enqueue_omnichannel_inbound(bot_id=bot.id, inbound=inbound)
        if task_id:
            queued_count += 1

    logger.info(
        "Omnichannel.Telegram.webhook | org={org} logged={n} queued={q} hash={hash}",
        org=organization_id,
        n=len(logged_ids),
        q=queued_count,
        hash=bot_token_hash[:12],
    )
    return TelegramWebhookResult(
        status="ok",
        logged=len(logged_ids),
        queued=queued_count,
        message_ids=logged_ids,
    )
