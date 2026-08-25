"""MessagingAdapter contract and unified ``message.received`` envelope (architecture §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import httpx

from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle


@dataclass
class MessageReceived:
    """Canonical inbound event produced by ``parseIncomingWebhook()``."""

    type: str = "message.received"
    provider: str = "wazzup"
    connection_id: str | None = None
    channel_id: str = ""
    channel_type: str = "whatsapp"
    chat_id: str = ""
    message_id: str = ""
    text: str = ""
    content_uri: str | None = None
    from_id: str = ""
    from_name: str = ""
    timestamp: str = ""
    is_echo: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "provider": self.provider,
            "connection_id": self.connection_id,
            "channel_id": self.channel_id,
            "channel_type": self.channel_type,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "text": self.text,
            "content_uri": self.content_uri,
            "from": {"id": self.from_id, "name": self.from_name},
            "timestamp": self.timestamp,
            "is_echo": self.is_echo,
        }


class MessagingAdapter(Protocol):
    provider: str

    async def connect(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        payload: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> TokenBundle: ...

    async def bind_event_handlers(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
    ) -> None: ...

    def parse_incoming_webhook(
        self,
        payload: dict[str, Any],
        *,
        connection_id: UUID | None = None,
    ) -> list[MessageReceived]: ...

    async def send_message(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        chat_id: str,
        text: str,
        channel_id: str | None = None,
        channel_type: str | None = None,
    ) -> dict[str, Any]: ...
