"""Message delivery extras in ``bot.credentials['_mpai_message_extras']``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.models.core_models import Bot

EXTRAS_KEY = "_mpai_message_extras"

DEFAULT_EXTRAS: dict[str, Any] = {
    "follow_up_enabled": False,
    "follow_up_delay_hours": 24,
    "split_delay_seconds": 1,
    "send_on_weekends": True,
}


def normalize_message_extras(raw: Any) -> dict[str, Any]:
    base = dict(DEFAULT_EXTRAS)
    if not isinstance(raw, dict):
        return base
    base["follow_up_enabled"] = bool(raw.get("follow_up_enabled", False))
    try:
        delay_h = int(raw.get("follow_up_delay_hours", 24))
    except (TypeError, ValueError):
        delay_h = 24
    base["follow_up_delay_hours"] = max(1, min(delay_h, 168))
    try:
        split_delay = int(raw.get("split_delay_seconds", 1))
    except (TypeError, ValueError):
        split_delay = 1
    base["split_delay_seconds"] = max(0, min(split_delay, 30))
    base["send_on_weekends"] = bool(raw.get("send_on_weekends", True))
    return base


def get_message_extras(bot: Bot | None) -> dict[str, Any]:
    if bot is None:
        return dict(DEFAULT_EXTRAS)
    credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
    return normalize_message_extras(credentials.get(EXTRAS_KEY))


def set_message_extras(bot: Bot, extras: dict[str, Any] | Any) -> dict[str, Any]:
    normalized = normalize_message_extras(extras)
    credentials = dict(bot.credentials or {})
    credentials[EXTRAS_KEY] = normalized
    bot.credentials = credentials
    flag_modified(bot, "credentials")
    return normalized


def split_outbound_text(text: str, *, enabled: bool) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if not enabled:
        return [cleaned]
    parts = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    return parts or [cleaned]
