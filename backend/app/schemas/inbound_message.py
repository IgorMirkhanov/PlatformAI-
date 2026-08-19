"""Unified inbound message contract — all channel webhooks normalize to this before Celery."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class InboundChannel(str, Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    WEB = "web"


class NormalizedInboundMessage(BaseModel):
    """
    Canonical payload every webhook adapter must produce before ``inbound_messages``.

    ``channel_user_id`` is the stable per-channel identity (Telegram chat_id, WA phone, web session).
    """

    channel: InboundChannel
    channel_user_id: str = Field(min_length=1, max_length=256)
    bot_id: uuid.UUID
    message_text: str = Field(default="", max_length=65535)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_celery_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel.value,
            "channel_user_id": self.channel_user_id,
            "bot_id": str(self.bot_id),
            "message_text": self.message_text,
            "metadata": self.metadata,
        }

    @classmethod
    def from_celery_dict(cls, data: dict[str, Any]) -> NormalizedInboundMessage | None:
        if not isinstance(data, dict) or not data.get("channel"):
            return None
        try:
            channel_raw = str(data["channel"]).strip().lower()
            channel = InboundChannel(channel_raw)
            return cls(
                channel=channel,
                channel_user_id=str(data["channel_user_id"]),
                bot_id=uuid.UUID(str(data["bot_id"])),
                message_text=str(data.get("message_text") or ""),
                metadata=dict(data.get("metadata") or {}),
            )
        except (ValueError, KeyError):
            return None
