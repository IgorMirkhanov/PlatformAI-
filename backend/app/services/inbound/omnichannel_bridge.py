"""Bridge omnichannel connector webhooks into the production Celery inbound pipeline."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.models.core_models import Bot, PlatformType
from app.schemas.omnichannel.message import InboundMessage
from app.services.inbound.normalizer import (
    attach_normalized,
    normalize_telegram,
    normalize_web_widget,
    normalize_whatsapp,
)
from app.tasks.webhook_tasks import process_inbound_message_task


_OMNI_CHANNEL_PLATFORM: dict[str, PlatformType] = {
    "telegram": PlatformType.TELEGRAM,
    "whatsapp": PlatformType.WHATSAPP,
    "web_chat": PlatformType.WEB_WIDGET,
}

_OMNI_HUB_CHANNEL: dict[str, HubChannelType] = {
    "telegram": HubChannelType.TELEGRAM,
    "whatsapp": HubChannelType.WABA,
    "web_chat": HubChannelType.WEB_WIDGET,
}


async def resolve_bot_for_omnichannel(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    channel: str,
) -> Bot | None:
    """Pick the active bot for this tenant + channel (prefer connected hub channel)."""
    channel_key = channel.strip().lower()
    platform = _OMNI_CHANNEL_PLATFORM.get(channel_key)
    hub_type = _OMNI_HUB_CHANNEL.get(channel_key)

    stmt = (
        select(Bot)
        .where(
            Bot.organization_id == organization_id,
            Bot.is_active.is_(True),
        )
        .order_by(Bot.created_at.desc())
    )
    if platform is not None:
        stmt = stmt.where(Bot.platform_type == platform)

    result = await db.execute(stmt)
    candidates = list(result.scalars().all())
    if not candidates:
        return None

    if hub_type is None:
        return candidates[0]

    bot_ids = [bot.id for bot in candidates]
    channel_result = await db.execute(
        select(BotChannel).where(
            BotChannel.bot_id.in_(bot_ids),
            BotChannel.channel_type == hub_type,
            BotChannel.status == HubChannelStatus.CONNECTED,
        )
    )
    connected = {row.bot_id: row for row in channel_result.scalars().all()}
    for bot in candidates:
        if bot.id in connected:
            return bot
    return candidates[0]


def _platform_type_for_channel(channel: str) -> str:
    mapping = {
        "telegram": "TELEGRAM",
        "whatsapp": "WHATSAPP",
        "web_chat": "WEB_WIDGET",
    }
    return mapping.get(channel.strip().lower(), channel.upper())


def enqueue_omnichannel_inbound(
    *,
    bot_id: uuid.UUID,
    inbound: InboundMessage,
) -> str | None:
    """
    Normalize an omnichannel ``InboundMessage`` and enqueue ``inbound_messages`` work.

    Returns Celery task id, or ``None`` when the message was ignored.
    """
    channel = inbound.channel.strip().lower()
    raw = inbound.raw_payload if isinstance(inbound.raw_payload, dict) else {}

    if channel == "telegram":
        normalized = normalize_telegram(
            bot_id=bot_id,
            chat_id=inbound.sender_id,
            message_text=inbound.content,
            username=inbound.sender_id,
            first_name=inbound.sender_name,
            raw_payload=raw,
        )
        payload = attach_normalized(
            {
                "bot_id": str(bot_id),
                "update": raw,
                "external_id": inbound.sender_id,
                "username": inbound.sender_id,
                "first_name": inbound.sender_name or inbound.sender_id,
                "message_text": inbound.content,
            },
            normalized,
        )
    elif channel == "whatsapp":
        normalized = normalize_whatsapp(
            bot_id=bot_id,
            phone=inbound.sender_id,
            message_text=inbound.content,
            client_name=inbound.sender_name,
            provider="whatsapp",
            raw_payload=raw,
        )
        payload = attach_normalized(
            {
                "bot_id": str(bot_id),
                "body": raw,
                "external_id": inbound.sender_id,
                "username": inbound.sender_id,
                "first_name": inbound.sender_name or inbound.sender_id,
                "message_text": inbound.content,
            },
            normalized,
        )
    elif channel in {"web_chat", "web", "web_widget"}:
        normalized = normalize_web_widget(
            bot_id=bot_id,
            session_id=inbound.sender_id,
            message_text=inbound.content,
            username=inbound.sender_name,
            raw_payload=raw,
        )
        payload = attach_normalized(
            {
                "bot_id": str(bot_id),
                "body": raw,
                "external_id": inbound.sender_id,
                "username": inbound.sender_name or inbound.sender_id,
                "message_text": inbound.content,
            },
            normalized,
        )
    else:
        logger.warning(
            "OmnichannelBridge.unsupported_channel | channel={channel} bot_id={bot_id}",
            channel=channel,
            bot_id=bot_id,
        )
        return None

    platform_type = _platform_type_for_channel(channel)
    task = process_inbound_message_task.apply_async(
        args=[str(bot_id), platform_type, payload],
        queue=settings.CELERY_INBOUND_QUEUE,
    )
    logger.info(
        "OmnichannelBridge.queued | task_id={task_id} bot_id={bot_id} channel={channel}",
        task_id=task.id,
        bot_id=bot_id,
        channel=channel,
    )
    return task.id
