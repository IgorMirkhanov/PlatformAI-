"""Build ``NormalizedInboundMessage`` from channel-specific webhook bodies."""

from __future__ import annotations

import uuid
from typing import Any

from app.schemas.inbound_message import InboundChannel, NormalizedInboundMessage
from app.utils.phone_utils import clean_phone_number


def normalize_telegram(
    *,
    bot_id: uuid.UUID,
    chat_id: str,
    message_text: str,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> NormalizedInboundMessage:
    display = " ".join(p for p in (first_name, last_name) if p).strip() or first_name or username
    return NormalizedInboundMessage(
        channel=InboundChannel.TELEGRAM,
        channel_user_id=str(chat_id),
        bot_id=bot_id,
        message_text=message_text,
        metadata={
            "hub_channel_type": "telegram",
            "username": username,
            "client_name": display,
            "first_name": first_name,
            "last_name": last_name,
            "raw_payload": raw_payload or {},
        },
    )


def normalize_whatsapp(
    *,
    bot_id: uuid.UUID,
    phone: str,
    message_text: str,
    client_name: str | None = None,
    provider: str = "whatsapp",
    raw_payload: dict[str, Any] | None = None,
) -> NormalizedInboundMessage:
    hub_type = provider or "whatsapp"
    return NormalizedInboundMessage(
        channel=InboundChannel.WHATSAPP,
        channel_user_id=str(phone),
        bot_id=bot_id,
        message_text=message_text,
        metadata={
            "hub_channel_type": hub_type,
            "client_name": client_name or phone,
            "provider": provider,
            "phone": phone,
            "raw_payload": raw_payload or {},
        },
    )


def normalize_web_widget(
    *,
    bot_id: uuid.UUID,
    session_id: str,
    message_text: str,
    username: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> NormalizedInboundMessage:
    return NormalizedInboundMessage(
        channel=InboundChannel.WEB,
        channel_user_id=str(session_id),
        bot_id=bot_id,
        message_text=message_text,
        metadata={
            "hub_channel_type": "web_widget",
            "username": username or "web-visitor",
            "client_name": username or "web-visitor",
            "raw_payload": raw_payload or {},
        },
    )


def normalize_wazzup_inbound(
    *,
    bot_id: uuid.UUID,
    inbound: dict[str, str],
    raw_body: dict[str, Any],
) -> NormalizedInboundMessage:
    phone = clean_phone_number(inbound.get("external_id")) or str(inbound["external_id"])
    normalized = normalize_whatsapp(
        bot_id=bot_id,
        phone=phone,
        message_text=str(inbound.get("message_text") or ""),
        client_name=str(inbound.get("first_name") or phone),
        provider="wazzup",
        raw_payload=raw_body,
    )
    normalized.metadata["channel_id"] = str(inbound.get("channel_id") or "")
    return normalized


def normalize_whatsapp_qr(
    *,
    bot_id: uuid.UUID,
    from_phone: str,
    message_text: str,
    push_name: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> NormalizedInboundMessage:
    phone = clean_phone_number(from_phone) or from_phone
    return normalize_whatsapp(
        bot_id=bot_id,
        phone=phone,
        message_text=message_text,
        client_name=push_name or phone,
        provider="whatsapp_qr",
        raw_payload=raw_payload or {},
    )


def attach_normalized(payload: dict[str, Any], normalized: NormalizedInboundMessage) -> dict[str, Any]:
    """Merge normalized fields into the Celery task payload."""
    merged = dict(payload)
    merged["normalized"] = normalized.to_celery_dict()
    merged.setdefault("channel", normalized.channel.value)
    merged.setdefault("channel_user_id", normalized.channel_user_id)
    merged.setdefault("external_id", normalized.channel_user_id)
    return merged
