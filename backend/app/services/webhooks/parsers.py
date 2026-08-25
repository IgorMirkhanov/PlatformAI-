"""Inbound webhook payload parsers (architecture spec §5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedInbound:
    provider: str
    reference_id: str
    external_message_id: str
    external_chat_id: str
    text: str
    raw: dict[str, Any]


def parse_telegram(payload: dict[str, Any]) -> ParsedInbound | None:
    message = payload.get("message") or payload.get("edited_message") or payload.get("channel_post")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    from_user = message.get("from") if isinstance(message.get("from"), dict) else {}
    bot_id = str(from_user.get("id") or "")
    # Routing key is the bot's numeric id from getMe, stored as reference_id.
    # Fallback: chat id is never used as channel reference — caller overlays bot reference.
    msg_id = str(message.get("message_id") or payload.get("update_id") or "")
    chat_id = str(chat.get("id") or "")
    text = str(message.get("text") or message.get("caption") or "")
    if not msg_id:
        return None
    return ParsedInbound(
        provider="telegram",
        reference_id=bot_id,
        external_message_id=msg_id,
        external_chat_id=chat_id,
        text=text,
        raw=payload,
    )


def parse_wazzup(payload: dict[str, Any]) -> ParsedInbound | None:
    messages = payload.get("messages")
    item = None
    if isinstance(messages, list) and messages:
        first = messages[0]
        if isinstance(first, dict):
            item = first
    if item is None and isinstance(payload, dict):
        item = payload
    channel_id = str(
        (item or {}).get("channelId")
        or payload.get("channelId")
        or (item or {}).get("channel_id")
        or ""
    ).strip()
    msg_id = str(
        (item or {}).get("messageId")
        or payload.get("messageId")
        or (item or {}).get("id")
        or ""
    ).strip()
    chat_id = str((item or {}).get("chatId") or (item or {}).get("chatType") or "").strip()
    text = str((item or {}).get("text") or (item or {}).get("message") or "")
    if not channel_id or not msg_id:
        return None
    return ParsedInbound(
        provider="wazzup",
        reference_id=channel_id,
        external_message_id=msg_id,
        external_chat_id=chat_id or msg_id,
        text=text,
        raw=payload,
    )


def parse_greenapi(payload: dict[str, Any]) -> ParsedInbound | None:
    instance = payload.get("instanceData") if isinstance(payload.get("instanceData"), dict) else {}
    body = payload.get("messageData") if isinstance(payload.get("messageData"), dict) else payload
    sender = payload.get("senderData") if isinstance(payload.get("senderData"), dict) else {}
    reference = str(
        instance.get("idInstance") or payload.get("idInstance") or payload.get("instanceId") or ""
    ).strip()
    msg_id = str(
        payload.get("idMessage")
        or (body.get("idMessage") if isinstance(body, dict) else "")
        or payload.get("id")
        or ""
    ).strip()
    chat_id = str(sender.get("chatId") or payload.get("chatId") or "").strip()
    text_obj = body.get("textMessageData") if isinstance(body, dict) else None
    text = ""
    if isinstance(text_obj, dict):
        text = str(text_obj.get("textMessage") or "")
    elif isinstance(body, dict):
        text = str(body.get("text") or body.get("message") or "")
    if not reference or not msg_id:
        return None
    return ParsedInbound(
        provider="greenapi",
        reference_id=reference,
        external_message_id=msg_id,
        external_chat_id=chat_id or msg_id,
        text=text,
        raw=payload,
    )


def parse_widget(payload: dict[str, Any]) -> ParsedInbound | None:
    reference = str(payload.get("widget_key") or payload.get("widgetKey") or "").strip()
    msg_id = str(payload.get("message_id") or payload.get("id") or "").strip()
    chat_id = str(payload.get("session_id") or payload.get("chat_id") or "").strip()
    text = str(payload.get("text") or payload.get("message") or "")
    if not reference or not msg_id:
        return None
    return ParsedInbound(
        provider="widget",
        reference_id=reference,
        external_message_id=msg_id,
        external_chat_id=chat_id or msg_id,
        text=text,
        raw=payload,
    )


PARSERS = {
    "telegram": parse_telegram,
    "wazzup": parse_wazzup,
    "greenapi": parse_greenapi,
    "widget": parse_widget,
    "web_widget": parse_widget,
}


def parse_inbound(provider: str, payload: dict[str, Any]) -> ParsedInbound | None:
    parser = PARSERS.get((provider or "").strip().lower())
    if parser is None:
        return None
    return parser(payload)
