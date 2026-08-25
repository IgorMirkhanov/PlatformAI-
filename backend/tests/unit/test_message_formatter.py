"""Telegram / WhatsApp formatters (commercial release spec §2)."""

from __future__ import annotations

from app.services.formatting.message_formatter import (
    ChannelType,
    MessageFormatter,
    TelegramFormatter,
    WhatsAppFormatter,
    split_preserving_markup,
)


def test_telegram_escapes_specials_outside_code() -> None:
    raw = "Price is 10.5_usd (now)!"
    out = TelegramFormatter.to_markdown_v2(raw)
    assert "\\." in out
    assert "\\_" in out
    assert "\\(" in out
    assert "\\!" in out


def test_telegram_preserves_code_fence() -> None:
    raw = "see ```a.b_c``` done."
    out = TelegramFormatter.escape_markdown_v2(raw)
    assert "```a.b_c```" in out
    assert "\\." in out


def test_telegram_long_text_splits_without_breaking_bold() -> None:
    paragraph = "hello **" + ("word " * 40) + "**\n\n"
    text = paragraph * 20
    assert len(text) > 4096
    parts = MessageFormatter.format_parts_for_channel(text, ChannelType.TELEGRAM)
    assert len(parts) >= 2
    assert all(len(part) <= 4096 for part in parts)
    joined_markers = "".join(parts).count("*")
    assert joined_markers % 2 == 0


def test_telegram_10000_chars_with_code_block() -> None:
    body = "intro\n```\n" + ("code line\n" * 200) + "```\n" + ("paragraph text. " * 800)
    assert len(body) > 10000
    parts = MessageFormatter.format_parts_for_channel(body, "telegram")
    assert all(len(part) <= 4096 for part in parts)
    assert sum(len(p) for p in parts) >= 4000


def test_whatsapp_converts_markdown() -> None:
    raw = "This is **bold** and `code` and ~~strike~~"
    out = WhatsAppFormatter.to_whatsapp_markdown(raw)
    assert "*bold*" in out
    assert '"code"' in out
    assert "~strike~" in out
    assert "**" not in out


def test_split_does_not_cut_mid_word_when_possible() -> None:
    text = ("alpha " * 200) + "\n\n" + ("bravo " * 200)
    parts = split_preserving_markup(text, 200)
    assert all(len(p) <= 200 for p in parts)
    assert not any(p.endswith("alph") for p in parts)
