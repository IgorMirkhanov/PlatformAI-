"""Message delivery extras in ``bot.credentials['_mpai_message_extras']``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.models.core_models import Bot

EXTRAS_KEY = "_mpai_message_extras"

FOLLOW_UP_FREQUENCIES = frozenset({"once_per_dialogue", "every_silence"})
FOLLOW_UP_OFF_HOURS_MODES = frozenset(
    {"defer_next_window", "send_anyway", "skip"}
)

DEFAULT_EXTRAS: dict[str, Any] = {
    "follow_up_enabled": False,
    "follow_up_delay_days": 0,
    "follow_up_delay_hours": 4,
    "follow_up_delay_minutes": 0,
    # Legacy total-hours field kept in sync for older callers.
    "follow_up_delay_hours_total": 4,
    "follow_up_send_count": 1,
    "follow_up_frequency": "once_per_dialogue",
    "follow_up_instructions": "",
    "follow_up_off_hours_mode": "defer_next_window",
    "split_delay_seconds": 1,
    "send_on_weekends": True,
}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def follow_up_delay_seconds(extras: dict[str, Any] | None) -> int:
    """Resolve silence delay in seconds (minimum 60s)."""
    data = extras if isinstance(extras, dict) else DEFAULT_EXTRAS
    days = max(0, min(_as_int(data.get("follow_up_delay_days"), 0), 30))
    hours = max(0, min(_as_int(data.get("follow_up_delay_hours"), 4), 23))
    minutes = max(0, min(_as_int(data.get("follow_up_delay_minutes"), 0), 59))
    total = days * 86400 + hours * 3600 + minutes * 60
    if total <= 0:
        # Backward compat: older configs only stored follow_up_delay_hours as 1..168.
        legacy = _as_int(data.get("follow_up_delay_hours_total"), 0)
        if legacy <= 0:
            legacy = _as_int(data.get("follow_up_delay_hours"), 4)
            # If value looks like legacy total-hours (>23), treat as hours total.
            if legacy > 23:
                total = legacy * 3600
            else:
                total = max(legacy, 1) * 3600
        else:
            total = legacy * 3600
    return max(60, min(total, 30 * 86400))


def normalize_message_extras(raw: Any) -> dict[str, Any]:
    base = dict(DEFAULT_EXTRAS)
    if not isinstance(raw, dict):
        return base

    base["follow_up_enabled"] = bool(raw.get("follow_up_enabled", False))

    # Prefer explicit D/H/M when any of them is present; else migrate legacy hours.
    has_dhm = any(
        key in raw
        for key in (
            "follow_up_delay_days",
            "follow_up_delay_minutes",
            "follow_up_delay_hours",
        )
    )
    if has_dhm:
        days = max(0, min(_as_int(raw.get("follow_up_delay_days"), 0), 30))
        # If only legacy total hours was saved historically as follow_up_delay_hours
        # with values like 24/48, split into days+hours when minutes absent.
        raw_hours = _as_int(raw.get("follow_up_delay_hours"), 4)
        minutes = max(0, min(_as_int(raw.get("follow_up_delay_minutes"), 0), 59))
        if (
            "follow_up_delay_days" not in raw
            and "follow_up_delay_minutes" not in raw
            and raw_hours > 23
        ):
            days = raw_hours // 24
            hours = raw_hours % 24
        else:
            hours = max(0, min(raw_hours, 23))
        base["follow_up_delay_days"] = days
        base["follow_up_delay_hours"] = hours
        base["follow_up_delay_minutes"] = minutes
    else:
        legacy_hours = max(1, min(_as_int(raw.get("follow_up_delay_hours"), 24), 168))
        base["follow_up_delay_days"] = legacy_hours // 24
        base["follow_up_delay_hours"] = legacy_hours % 24
        base["follow_up_delay_minutes"] = 0

    total_hours = (
        base["follow_up_delay_days"] * 24
        + base["follow_up_delay_hours"]
        + (1 if base["follow_up_delay_minutes"] else 0)
    )
    base["follow_up_delay_hours_total"] = max(1, min(total_hours, 168 * 2))

    base["follow_up_send_count"] = max(
        1, min(_as_int(raw.get("follow_up_send_count"), 1), 5)
    )
    frequency = str(raw.get("follow_up_frequency") or "once_per_dialogue").strip()
    base["follow_up_frequency"] = (
        frequency if frequency in FOLLOW_UP_FREQUENCIES else "once_per_dialogue"
    )
    instructions = raw.get("follow_up_instructions")
    base["follow_up_instructions"] = (
        str(instructions).strip()[:4000] if instructions is not None else ""
    )
    off_hours = str(
        raw.get("follow_up_off_hours_mode") or "defer_next_window"
    ).strip()
    base["follow_up_off_hours_mode"] = (
        off_hours if off_hours in FOLLOW_UP_OFF_HOURS_MODES else "defer_next_window"
    )

    base["split_delay_seconds"] = max(
        0, min(_as_int(raw.get("split_delay_seconds"), 1), 30)
    )
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
