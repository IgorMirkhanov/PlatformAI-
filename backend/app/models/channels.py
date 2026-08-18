"""Omnichannel bot_channels persistence (Telegram, WABA, WhatsApp QR, etc.)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class HubChannelType(str, enum.Enum):
    TELEGRAM = "telegram"
    TELEGRAM_BUSINESS = "telegram_business"
    INSTAGRAM = "instagram"
    WAZZUP = "wazzup"
    WABA = "waba"
    WHATSAPP_QR = "whatsapp_qr"
    WEB_WIDGET = "web_widget"
    API = "api"
    CALLS = "calls"


class HubChannelStatus(str, enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    PENDING = "pending"


HUB_CHANNEL_TYPES: tuple[HubChannelType, ...] = (
    HubChannelType.TELEGRAM,
    HubChannelType.TELEGRAM_BUSINESS,
    HubChannelType.WAZZUP,
    HubChannelType.WHATSAPP_QR,
    HubChannelType.INSTAGRAM,
    HubChannelType.WABA,
    HubChannelType.CALLS,
    HubChannelType.API,
    HubChannelType.WEB_WIDGET,
)


class BotChannel(Base):
    """Per-bot messenger / social channel binding with encrypted credentials."""

    __tablename__ = "bot_channels"
    __table_args__ = (
        UniqueConstraint("bot_id", "channel_type", name="uq_bot_channels_bot_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[HubChannelType] = mapped_column(
        Enum(HubChannelType, name="hub_channel_type", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    status: Mapped[HubChannelStatus] = mapped_column(
        Enum(HubChannelStatus, name="hub_channel_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=HubChannelStatus.DISCONNECTED,
        server_default=HubChannelStatus.DISCONNECTED.value,
        index=True,
    )
    encrypted_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    bot: Mapped[Any] = relationship("Bot", back_populates="channels")
