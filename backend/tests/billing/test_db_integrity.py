"""Unit tests for billing idempotency helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from app.core.db_integrity import is_unique_violation


def test_is_unique_violation_detects_pgcode_23505() -> None:
    orig = MagicMock()
    orig.pgcode = "23505"
    exc = IntegrityError("insert", {}, orig)
    assert is_unique_violation(exc) is True


def test_is_unique_violation_false_for_other_errors() -> None:
    orig = MagicMock()
    orig.pgcode = "23503"
    exc = IntegrityError("insert", {}, orig)
    assert is_unique_violation(exc) is False
