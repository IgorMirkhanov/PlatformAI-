"""Unit tests: tool-debug text must never reach messengers."""

from __future__ import annotations

import pytest

from app.services.llm.tool_reply_sanitize import (
    is_tool_debug_text,
    sanitize_outbound_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Called tools: save_lead_to_crm", True),
        ("called tools: foo, bar", True),
        ("  Called tools: x  ", True),
        ("Отлично, записал вас на завтра!", False),
        ("", False),
        (None, False),
        ("I called tools earlier but this is fine", False),
    ],
)
def test_is_tool_debug_text(text: str | None, expected: bool) -> None:
    assert is_tool_debug_text(text) is expected


def test_sanitize_keeps_natural_reply() -> None:
    assert (
        sanitize_outbound_text("Записал вас на 15:00.")
        == "Записал вас на 15:00."
    )


def test_sanitize_replaces_called_tools_with_booking_fallback() -> None:
    out = sanitize_outbound_text(
        "Called tools: save_lead_to_crm",
        tools_executed=["save_lead_to_crm"],
        booking_ok=True,
    )
    assert "Called tools" not in out
    assert "заявк" in out.lower() or "Записал" in out


def test_sanitize_replaces_called_tools_with_generic_fallback() -> None:
    out = sanitize_outbound_text(
        "Called tools: custom_fn",
        tools_executed=["custom_fn"],
        booking_ok=False,
    )
    assert "Called tools" not in out
    assert len(out) > 0


def test_sanitize_empty_without_tools() -> None:
    assert sanitize_outbound_text("Called tools: x") == ""
    assert sanitize_outbound_text("") == ""
