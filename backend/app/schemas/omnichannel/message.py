"""Universal Omnichannel message contracts — channel-agnostic."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChannelName = Literal["whatsapp", "telegram", "web_chat"] | str
MessageDirection = Literal["inbound", "outbound"]


class InboundMessage(BaseModel):
    """Normalized inbound event from any messenger / widget."""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(..., min_length=1, max_length=64)
    channel_message_id: str = Field(..., min_length=1, max_length=255)
    organization_id: uuid.UUID
    sender_id: str = Field(..., min_length=1, max_length=255)
    sender_name: str | None = None
    content: str = Field(default="", max_length=100_000)
    media_urls: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class OutboundMessage(BaseModel):
    """Normalized outbound payload for any channel connector."""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(..., min_length=1, max_length=64)
    recipient_id: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=0, max_length=100_000)
    media_urls: list[str] | None = None
    reply_to_message_id: str | None = None
    # Optional WhatsApp HSM / approved template (ignored by other connectors).
    template_name: str | None = None
    template_language: str | None = Field(default="en_US", max_length=32)
    template_components: list[dict[str, Any]] | None = None
    # Optional Telegram parse mode (Markdown / HTML / MarkdownV2).
    parse_mode: str | None = Field(default=None, max_length=32)
