"""Persistent Omnichannel dialogue log (channel-agnostic)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OmnichannelMessageLog(Base):
    """
    Append-only history of inbound/outbound Omnichannel messages.

    Business logic and Flow Builder should read this log (or InboundMessage /
    OutboundMessage DTOs) — never vendor webhook JSON directly.
    """

    __tablename__ = "omnichannel_message_logs"
    __table_args__ = (
        Index("ix_omnichannel_message_logs_organization_id", "organization_id"),
        Index(
            "ix_omnichannel_message_logs_org_channel_contact",
            "organization_id",
            "channel",
            "sender_recipient",
        ),
        Index("ix_omnichannel_message_logs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
