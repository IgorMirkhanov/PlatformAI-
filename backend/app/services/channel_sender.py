"""ChannelSenderFactory — format then dispatch. Orchestrator never sees messengers."""

from __future__ import annotations

from app.schemas.inbound_message import InboundChannel
from app.services.formatting.message_formatter import ChannelType, MessageFormatter


def channel_type_for_inbound(channel: InboundChannel | str, *, hub_type: str | None = None) -> str:
    raw = channel.value if isinstance(channel, InboundChannel) else str(channel or "").lower()
    hub = (hub_type or "").lower()
    if raw == InboundChannel.TELEGRAM.value or hub in {"telegram", "telegram_business"}:
        return ChannelType.TELEGRAM.value
    if hub in {"wazzup", "greenapi", "whatsapp", "instagram"}:
        return hub if hub != "whatsapp" else ChannelType.WHATSAPP.value
    if raw == InboundChannel.WHATSAPP.value:
        return ChannelType.WHATSAPP.value
    return ChannelType.WIDGET.value


class ChannelSenderFactory:
    @staticmethod
    def format_outbound(text: str, *, channel: InboundChannel | str, hub_type: str | None = None) -> list[str]:
        mapped = channel_type_for_inbound(channel, hub_type=hub_type)
        return MessageFormatter.format_parts_for_channel(text, mapped)
