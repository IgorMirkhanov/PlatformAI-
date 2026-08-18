"""PostgreSQL integrity error helpers."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError


def is_unique_violation(exc: IntegrityError) -> bool:
    """Return True when ``exc`` is a PostgreSQL unique-constraint violation (23505)."""
    orig = getattr(exc, "orig", None)
    if orig is not None and getattr(orig, "pgcode", None) == "23505":
        return True
    message = str(exc).lower()
    return "unique" in message or "duplicate key" in message
