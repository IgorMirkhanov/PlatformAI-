"""Pydantic schemas for the Omnichannel Integration Hub."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.channels import HubChannelStatus, HubChannelType


class HubChannelStatusItem(BaseModel):
    channel_type: HubChannelType
    status: HubChannelStatus
    connected: bool
    reference_id: str | None = None
    meta_data: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None
    webhook_url: str | None = None


class ChannelConnectRequest(BaseModel):
    """Credential payload for connecting a hub channel."""

    token: str | None = Field(default=None, min_length=1, max_length=1024)
    reference_id: str | None = Field(default=None, max_length=255)
    phone_number_id: str | None = Field(default=None, max_length=128)
    business_account_id: str | None = Field(default=None, max_length=128)
    access_token: str | None = Field(default=None, max_length=1024)
    verify_token: str | None = Field(default=None, max_length=128)
    page_id: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=512)
    meta_data: dict[str, Any] = Field(default_factory=dict)


class ChannelConnectResponse(BaseModel):
    success: bool = True
    bot_id: uuid.UUID
    channel_type: HubChannelType
    status: HubChannelStatus
    connected: bool
    reference_id: str | None = None
    webhook_url: str | None = None
    message: str


class ChannelDisconnectResponse(BaseModel):
    success: bool = True
    bot_id: uuid.UUID
    channel_type: HubChannelType
    status: HubChannelStatus
    connected: bool
    message: str


class HubChannelsResponse(BaseModel):
    success: bool = True
    bot_id: uuid.UUID
    channels: list[HubChannelStatusItem]


class WhatsAppQrWsFrame(BaseModel):
    """WebSocket / SSE status frame for WhatsApp QR pairing."""

    event: str
    status: str
    qr_base64: str | None = None
    message: str | None = None
    reference_id: str | None = None
    session_id: str | None = None
