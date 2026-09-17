"""Per-bot Control tab settings stored in ``bot.credentials['_mpai_control']``."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.core_models import Bot

CONTROL_KEY = "_mpai_control"

DEFAULT_CONTROL_CONFIG: dict[str, Any] = {
    "history": {
        "message_limit": 20,
        "time_window_days": 7,
    },
    "spam_protection": {
        "enabled": False,
        "limit_message": "Секунду, принимаю информацию...",
        "message_count": 5,
        "duration_seconds": 10,
    },
    "operator_intervention": {
        "pause_on_operator_message": True,
        "ignore_first_operator_message": False,
        "auto_resume_enabled": False,
        "auto_resume_days": 0,
        "auto_resume_hours": 3,
        "auto_resume_minutes": 0,
        "resume_message_enabled": False,
        "resume_message": "Добрый день!",
        "exception_phrases_enabled": False,
        "exception_phrases": [],
    },
    "keyword_dialog": {
        "stop_enabled": False,
        "stop_phrases": [],
        "resume_enabled": False,
        "resume_phrases": [],
    },
}


def _as_int(value: Any, default: int, *, min_v: int | None = None, max_v: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if min_v is not None:
        parsed = max(min_v, parsed)
    if max_v is not None:
        parsed = min(max_v, parsed)
    return parsed


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text[:500])
        if len(out) >= 50:
            break
    return out


def normalize_control_config(raw: Any) -> dict[str, Any]:
    base = deepcopy(DEFAULT_CONTROL_CONFIG)
    if not isinstance(raw, dict):
        return base

    history = raw.get("history") if isinstance(raw.get("history"), dict) else {}
    spam = raw.get("spam_protection") if isinstance(raw.get("spam_protection"), dict) else {}
    op = raw.get("operator_intervention") if isinstance(raw.get("operator_intervention"), dict) else {}
    kw = raw.get("keyword_dialog") if isinstance(raw.get("keyword_dialog"), dict) else {}

    base["history"]["message_limit"] = _as_int(
        history.get("message_limit", base["history"]["message_limit"]),
        20,
        min_v=1,
        max_v=200,
    )
    base["history"]["time_window_days"] = _as_int(
        history.get("time_window_days", base["history"]["time_window_days"]),
        7,
        min_v=1,
        max_v=90,
    )

    base["spam_protection"]["enabled"] = bool(spam.get("enabled", False))
    base["spam_protection"]["limit_message"] = str(
        spam.get("limit_message") or base["spam_protection"]["limit_message"]
    )[:2000]
    base["spam_protection"]["message_count"] = _as_int(
        spam.get("message_count", 5), 5, min_v=1, max_v=100
    )
    base["spam_protection"]["duration_seconds"] = _as_int(
        spam.get("duration_seconds", 10), 10, min_v=1, max_v=3600
    )

    base["operator_intervention"]["pause_on_operator_message"] = bool(
        op.get("pause_on_operator_message", True)
    )
    base["operator_intervention"]["ignore_first_operator_message"] = bool(
        op.get("ignore_first_operator_message", False)
    )
    base["operator_intervention"]["auto_resume_enabled"] = bool(op.get("auto_resume_enabled", False))
    base["operator_intervention"]["auto_resume_days"] = _as_int(
        op.get("auto_resume_days", 0), 0, min_v=0, max_v=30
    )
    base["operator_intervention"]["auto_resume_hours"] = _as_int(
        op.get("auto_resume_hours", 3), 3, min_v=0, max_v=23
    )
    base["operator_intervention"]["auto_resume_minutes"] = _as_int(
        op.get("auto_resume_minutes", 0), 0, min_v=0, max_v=59
    )
    base["operator_intervention"]["resume_message_enabled"] = bool(
        op.get("resume_message_enabled", False)
    )
    base["operator_intervention"]["resume_message"] = str(
        op.get("resume_message") or base["operator_intervention"]["resume_message"]
    )[:2000]
    base["operator_intervention"]["exception_phrases_enabled"] = bool(
        op.get("exception_phrases_enabled", False)
    )
    base["operator_intervention"]["exception_phrases"] = _as_str_list(op.get("exception_phrases"))

    base["keyword_dialog"]["stop_enabled"] = bool(kw.get("stop_enabled", False))
    base["keyword_dialog"]["stop_phrases"] = _as_str_list(kw.get("stop_phrases"))
    base["keyword_dialog"]["resume_enabled"] = bool(kw.get("resume_enabled", False))
    base["keyword_dialog"]["resume_phrases"] = _as_str_list(kw.get("resume_phrases"))
    return base


def get_control_config(bot: Bot | None) -> dict[str, Any]:
    if bot is None:
        return deepcopy(DEFAULT_CONTROL_CONFIG)
    credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
    return normalize_control_config(credentials.get(CONTROL_KEY))


def set_control_config(bot: Bot, config: dict[str, Any] | Any) -> dict[str, Any]:
    if hasattr(config, "model_dump"):
        raw = config.model_dump()
    elif isinstance(config, dict):
        raw = config
    else:
        raw = {}
    normalized = normalize_control_config(raw)
    credentials = dict(bot.credentials or {})
    credentials[CONTROL_KEY] = normalized
    bot.credentials = credentials
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(bot, "credentials")
    return normalized


def phrase_matches(message: str, phrases: list[str]) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    for phrase in phrases:
        needle = phrase.strip().lower()
        if needle and needle in text:
            return True
    return False


def auto_resume_timedelta(control: dict[str, Any]) -> timedelta:
    op = control.get("operator_intervention") or {}
    return timedelta(
        days=int(op.get("auto_resume_days") or 0),
        hours=int(op.get("auto_resume_hours") or 0),
        minutes=int(op.get("auto_resume_minutes") or 0),
    )


def history_cutoff(control: dict[str, Any]) -> datetime | None:
    days = int((control.get("history") or {}).get("time_window_days") or 0)
    if days <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def history_message_limit(control: dict[str, Any], fallback: int) -> int:
    limit = int((control.get("history") or {}).get("message_limit") or fallback)
    return max(1, min(200, limit))
