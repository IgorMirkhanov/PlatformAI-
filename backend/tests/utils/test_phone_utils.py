"""Tests for phone normalization."""

from app.utils.phone_utils import clean_phone_number


def test_clean_phone_strips_formatting() -> None:
    assert clean_phone_number("+7 (707) 123-45-67") == "+77071234567"


def test_clean_phone_local_ten_digits() -> None:
    assert clean_phone_number("7071234567") == "+77071234567"


def test_clean_phone_eight_prefix() -> None:
    assert clean_phone_number("87071234567") == "+77071234567"


def test_clean_phone_invalid_returns_none() -> None:
    assert clean_phone_number("") is None
    assert clean_phone_number("abc") is None
    assert clean_phone_number("123") is None
