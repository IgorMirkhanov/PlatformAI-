"""Human handoff — pause AI and notify operators."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core_models import Bot, Client
from app.models.operator_notification import OperatorNotificationChannel


class ConversationNotFoundError(LookupError):
    pass


async def escalate_to_human(conversation_id: uuid.UUID, db: AsyncSession) -> Client:
    """
    Mark the conversation as escalated, stop AI auto-replies, notify operators.

    ``conversation_id`` is ``clients.id`` (inbox session).
    """
    client = await db.get(Client, conversation_id)
    if client is None:
        raise ConversationNotFoundError(str(conversation_id))

    client.is_paused_by_operator = True
    client.conversation_status = "escalated"
    await db.flush()

    bot = await db.get(Bot, client.bot_id)
    org_id = getattr(bot, "organization_id", None) if bot is not None else None
    if org_id is not None:
        await _notify_operators(
            db,
            organization_id=org_id,
            conversation_id=client.id,
            bot_name=getattr(bot, "name", None) or "bot",
            external_id=client.external_id,
        )
    logger.info(
        "Conversation.escalated | client_id={client_id} bot_id={bot_id}",
        client_id=client.id,
        bot_id=client.bot_id,
    )
    return client


async def _notify_operators(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    conversation_id: uuid.UUID,
    bot_name: str,
    external_id: str,
) -> None:
    stmt = select(OperatorNotificationChannel).where(
        OperatorNotificationChannel.organization_id == organization_id,
        OperatorNotificationChannel.is_active.is_(True),
    )
    channels = list((await db.scalars(stmt)).all())
    text = (
        f"Handoff: бот «{bot_name}» передал диалог оператору.\n"
        f"conversation_id={conversation_id}\n"
        f"external_id={external_id}"
    )
    token = (
        getattr(settings, "OPERATOR_NOTIFY_BOT_TOKEN", None)
        or getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        or ""
    ).strip()
    for channel in channels:
        try:
            if channel.channel_type.lower() == "telegram" and token:
                url = f"{settings.TELEGRAM_API_BASE}/bot{token}/sendMessage"
                async with httpx.AsyncClient(timeout=10.0) as http:
                    await http.post(
                        url,
                        json={"chat_id": channel.target_chat_id, "text": text[:3500]},
                    )
            elif channel.webhook_url:
                async with httpx.AsyncClient(timeout=10.0) as http:
                    await http.post(
                        channel.webhook_url,
                        json={
                            "event": "conversation_escalated",
                            "conversation_id": str(conversation_id),
                            "organization_id": str(organization_id),
                            "text": text,
                        },
                    )
        except Exception as exc:
            logger.warning(
                "OperatorNotify.failed | channel={id} error={error}",
                id=channel.id,
                error=str(exc),
            )
