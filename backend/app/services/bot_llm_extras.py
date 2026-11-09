"""LLM extras (media recognition + advanced knobs) in ``bot.credentials``.

Stored under ``_mpai_llm_extras`` so we do not need a migration for first client UX.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.models.core_models import Bot

EXTRAS_KEY = "_mpai_llm_extras"

DEFAULT_EXTRAS: dict[str, Any] = {
    "use_custom_api_key": False,
    "recognize_audio": False,
    "recognize_images": False,
    "recognize_files": False,
    "audio_engine": "whisper",
    "audio_language": "universal",
    "max_tokens": 1000,
    "top_p": 1.0,
}


def normalize_llm_extras(raw: Any) -> dict[str, Any]:
    base = dict(DEFAULT_EXTRAS)
    if not isinstance(raw, dict):
        return base
    base["use_custom_api_key"] = bool(raw.get("use_custom_api_key", False))
    base["recognize_audio"] = bool(raw.get("recognize_audio", False))
    base["recognize_images"] = bool(raw.get("recognize_images", False))
    base["recognize_files"] = bool(raw.get("recognize_files", False))
    engine = str(raw.get("audio_engine") or "whisper").strip().lower()
    base["audio_engine"] = engine if engine in {"whisper", "gpt4o_audio"} else "whisper"
    lang = str(raw.get("audio_language") or "universal").strip().lower()
    base["audio_language"] = lang if lang in {"universal", "ru", "en", "kk"} else "universal"
    try:
        max_tokens = int(raw.get("max_tokens", 1000))
    except (TypeError, ValueError):
        max_tokens = 1000
    base["max_tokens"] = max(64, min(max_tokens, 4096))
    try:
        top_p = float(raw.get("top_p", 1.0))
    except (TypeError, ValueError):
        top_p = 1.0
    base["top_p"] = max(0.0, min(top_p, 1.0))
    return base


def get_llm_extras(bot: Bot | None) -> dict[str, Any]:
    if bot is None:
        return dict(DEFAULT_EXTRAS)
    credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
    return normalize_llm_extras(credentials.get(EXTRAS_KEY))


def set_llm_extras(bot: Bot, extras: dict[str, Any] | Any) -> dict[str, Any]:
    normalized = normalize_llm_extras(extras)
    credentials = dict(bot.credentials or {})
    credentials[EXTRAS_KEY] = normalized
    bot.credentials = credentials
    flag_modified(bot, "credentials")
    return normalized


def media_recognition_allowed(bot: Bot | None, content_type: str) -> bool:
    extras = get_llm_extras(bot)
    kind = (content_type or "").lower()
    if kind in {"voice", "audio"}:
        return bool(extras["recognize_audio"])
    if kind in {"photo", "image", "sticker"}:
        return bool(extras["recognize_images"])
    if kind in {"document", "file"}:
        return bool(extras["recognize_files"])
    return True
