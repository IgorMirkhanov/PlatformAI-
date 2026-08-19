"""Phone normalization helpers for CRM integrations."""

from __future__ import annotations

import re

_NON_DIGIT = re.compile(r"\D")


def clean_phone_number(phone: str | None) -> str | None:
    """
    Strip formatting and return E.164 when possible (``+77071234567``).

    Returns ``None`` when the input is empty or too short/long for a real number.
    """
    raw = (phone or "").strip()
    if not raw:
        return None

    # Keep leading +, drop everything else non-digit.
    if raw.startswith("+"):
        digits = _NON_DIGIT.sub("", raw[1:])
        if not digits:
            return None
        normalized = f"+{digits}"
    else:
        digits = _NON_DIGIT.sub("", raw)
        if not digits:
            return None
        # Local KZ/RU: 8XXXXXXXXXX → +7XXXXXXXXXX, 10-digit → +7XXXXXXXXXX
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        elif len(digits) == 10:
            digits = "7" + digits
        normalized = f"+{digits}"

    body = normalized[1:]
    if len(body) < 10 or len(body) > 15:
        return None
    return normalized
