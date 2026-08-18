"""Omnichannel message log persistence helpers."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.omnichannel.message_log import OmnichannelMessageLog
from app.schemas.omnichannel.message import InboundMessage, OutboundMessage

DIRECTION_INBOUND = "inbound"
DIRECTION_OUTBOUND = "outbound"


class MessageLogService:
    """Append / query OmnichannelMessageLog with tenant scoping."""

    async def log_inbound(
        self,
        db: AsyncSession,
        message: InboundMessage,
    ) -> OmnichannelMessageLog:
        row = OmnichannelMessageLog(
            id=uuid.uuid4(),
            organization_id=message.organization_id,
            channel=message.channel,
            direction=DIRECTION_INBOUND,
            sender_recipient=message.sender_id,
            content=message.content,
            raw_data={
                "channel_message_id": message.channel_message_id,
                "sender_name": message.sender_name,
                "media_urls": message.media_urls,
                "timestamp": message.timestamp.isoformat(),
                "raw_payload": message.raw_payload,
            },
        )
        db.add(row)
        await db.flush()
        await db.commit()
        await db.refresh(row)
        return row

    async def log_outbound(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        message: OutboundMessage,
        *,
        raw_data: dict[str, Any] | None = None,
    ) -> OmnichannelMessageLog:
        row = OmnichannelMessageLog(
            id=uuid.uuid4(),
            organization_id=organization_id,
            channel=message.channel,
            direction=DIRECTION_OUTBOUND,
            sender_recipient=message.recipient_id,
            content=message.content,
            raw_data=raw_data
            or {
                "media_urls": message.media_urls,
                "reply_to_message_id": message.reply_to_message_id,
            },
        )
        db.add(row)
        await db.flush()
        await db.commit()
        await db.refresh(row)
        return row

    async def list_for_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        channel: str | None = None,
        sender_recipient: str | None = None,
        limit: int = 100,
    ) -> list[OmnichannelMessageLog]:
        stmt = select(OmnichannelMessageLog).where(
            OmnichannelMessageLog.organization_id == organization_id
        )
        if channel:
            stmt = stmt.where(OmnichannelMessageLog.channel == channel)
        if sender_recipient:
            stmt = stmt.where(OmnichannelMessageLog.sender_recipient == sender_recipient)
        stmt = stmt.order_by(OmnichannelMessageLog.created_at.desc()).limit(max(1, min(limit, 500)))
        result = await db.execute(stmt)
        return list(result.scalars().all())


message_log_service = MessageLogService()
