"""Channel-specific message formatting. Orchestrator stays channel-agnostic."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import Enum

TELEGRAM_LIMIT = 4096
WHATSAPP_LIMIT = 4096
TELEGRAM_V2_SPECIALS = r"_*[]()~`>#+-=|{}.!"


class ChannelType(str, Enum):
    TELEGRAM = "telegram"
    WAZZUP = "wazzup"
    GREENAPI = "greenapi"
    WHATSAPP = "whatsapp"
    WIDGET = "widget"
    WEB = "web"


class BaseChannelFormatter(ABC):
    @abstractmethod
    def format(self, text: str) -> str:
        raise NotImplementedError

    def split(self, text: str, limit: int) -> list[str]:
        return split_preserving_markup(text, limit)


class TelegramFormatter(BaseChannelFormatter):
    """MarkdownV2: escape specials outside code fences, split at 4096."""

    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        if not text:
            return ""
        parts: list[str] = []
        fence = re.split(r"(```.*?```|`[^`]*`)", text, flags=re.DOTALL)
        for i, chunk in enumerate(fence):
            if i % 2 == 1:
                parts.append(chunk)
                continue
            escaped = []
            for ch in chunk:
                if ch in TELEGRAM_V2_SPECIALS:
                    escaped.append("\\" + ch)
                else:
                    escaped.append(ch)
            parts.append("".join(escaped))
        return "".join(parts)

    @staticmethod
    def to_markdown_v2(text: str) -> str:
        converted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text or "", flags=re.DOTALL)
        return TelegramFormatter.escape_markdown_v2(converted)

    def format(self, text: str) -> str:
        return self.to_markdown_v2(text)


class WhatsAppFormatter(BaseChannelFormatter):
    """Internal markdown → WhatsApp (*bold*, _italic_, no fenced code)."""

    @staticmethod
    def to_whatsapp_markdown(text: str) -> str:
        src = text or ""
        src = re.sub(r"```(?:\w+)?\n?(.*?)```", lambda m: f"\"{m.group(1).strip()}\"", src, flags=re.DOTALL)
        src = re.sub(r"`([^`]+)`", r'"\1"', src)
        src = re.sub(r"\*\*(.+?)\*\*", r"*\1*", src, flags=re.DOTALL)
        src = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"*\1*", src, flags=re.DOTALL)
        src = re.sub(r"~~(.+?)~~", r"~\1~", src, flags=re.DOTALL)
        return src

    def format(self, text: str) -> str:
        return self.to_whatsapp_markdown(text)


class WidgetFormatter(BaseChannelFormatter):
    def format(self, text: str) -> str:
        return text or ""


def split_preserving_markup(text: str, limit: int) -> list[str]:
    """Split on paragraph / whitespace boundaries without breaking **pairs** mid-token."""
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    pair_tokens = ("```", "**", "`")
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 3:
            cut = window.rfind("\n")
        if cut < limit // 3:
            cut = window.rfind(" ")
        if cut < 1:
            cut = limit
        candidate = remaining[:cut].rstrip()
        if not candidate:
            candidate = remaining[:limit]
            cut = len(candidate)
        for token in pair_tokens:
            if candidate.count(token) % 2 == 1:
                last = candidate.rfind(token)
                if last > 0:
                    candidate = candidate[:last].rstrip()
                    cut = len(candidate) if candidate else cut
        if not candidate:
            candidate = remaining[:limit]
            cut = len(candidate)
        chunks.append(candidate)
        remaining = remaining[cut:].lstrip()
    return [c for c in chunks if c]


class MessageFormatter:
    @staticmethod
    def format_for_channel(text: str, channel_type: ChannelType | str) -> str:
        key = channel_type.value if isinstance(channel_type, ChannelType) else str(channel_type or "").lower()
        if key in {ChannelType.TELEGRAM.value, "telegram_business"}:
            return TelegramFormatter.to_markdown_v2(text)
        if key in {
            ChannelType.WAZZUP.value,
            ChannelType.GREENAPI.value,
            ChannelType.WHATSAPP.value,
            "instagram",
        }:
            return WhatsAppFormatter.to_whatsapp_markdown(text)
        return text or ""

    @staticmethod
    def format_parts_for_channel(text: str, channel_type: ChannelType | str) -> list[str]:
        key = channel_type.value if isinstance(channel_type, ChannelType) else str(channel_type or "").lower()
        if key in {ChannelType.TELEGRAM.value, "telegram_business"}:
            converted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text or "", flags=re.DOTALL)
            parts = split_preserving_markup(converted, TELEGRAM_LIMIT - 256)
            escaped: list[str] = []
            for part in parts:
                formatted = TelegramFormatter.escape_markdown_v2(part)
                if len(formatted) <= TELEGRAM_LIMIT:
                    escaped.append(formatted)
                else:
                    escaped.extend(split_preserving_markup(formatted, TELEGRAM_LIMIT))
            return [p for p in escaped if p]
        if key in {
            ChannelType.WAZZUP.value,
            ChannelType.GREENAPI.value,
            ChannelType.WHATSAPP.value,
            "instagram",
        }:
            formatted = WhatsAppFormatter.to_whatsapp_markdown(text)
            return split_preserving_markup(formatted, WHATSAPP_LIMIT)
        body = text or ""
        return [body] if body else []
