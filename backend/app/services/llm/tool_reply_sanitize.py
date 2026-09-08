"""Helpers to keep tool-call debug strings out of user-facing messenger replies."""

from __future__ import annotations

import re

_CALLED_TOOLS_RE = re.compile(r"^\s*Called tools\s*:", re.IGNORECASE)
_DEFAULT_TOOL_FALLBACK_RU = (
    "Готово — я всё обработал. Если нужно что-то уточнить, напишите мне."
)
_BOOKING_TOOL_FALLBACK_RU = (
    "Отлично! Записал вас на консультацию и зафиксировал заявку. "
    "Наш менеджер свяжется с вами."
)


def is_tool_debug_text(text: str | None) -> bool:
    """True when ``text`` is the legacy OpenAI-client placeholder, not a user reply."""
    if not text:
        return False
    return bool(_CALLED_TOOLS_RE.match(text.strip()))


def sanitize_outbound_text(
    text: str | None,
    *,
    tools_executed: list[str] | None = None,
    booking_ok: bool = False,
    fallback: str | None = None,
) -> str:
    """Strip ``Called tools: …`` placeholders; never return that string to messengers."""
    cleaned = (text or "").strip()
    if cleaned and not is_tool_debug_text(cleaned):
        return cleaned
    if booking_ok:
        return _BOOKING_TOOL_FALLBACK_RU
    if tools_executed:
        return fallback or _DEFAULT_TOOL_FALLBACK_RU
    return ""
