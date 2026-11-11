"""Telegram report chats captured from a /set_ command and from membership updates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.bot_workspace_config import (
    apply_telegram_update_to_chats,
    claim_telegram_bind_command,
    get_workspace,
    issue_telegram_report_bind,
    normalize_report_chat_id,
)


def test_normalize_report_chat_id_accepts_group_ids() -> None:
    assert normalize_report_chat_id(" -1004470066766 ") == "-1004470066766"


def test_normalize_report_chat_id_rejects_names() -> None:
    with pytest.raises(ValueError):
        normalize_report_chat_id("мой чат")


def test_group_message_without_command_is_not_connected() -> None:
    update = {
        "message": {
            "text": "привет",
            "chat": {"id": -1003905085393, "type": "supergroup", "title": "Отчёты"},
        }
    }
    assert apply_telegram_update_to_chats([], update) == []


def _bot(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr("sqlalchemy.orm.attributes.flag_modified", lambda *_a, **_k: None)
    return SimpleNamespace(credentials={})


def test_set_command_binds_the_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _bot(monkeypatch)
    issued = issue_telegram_report_bind(bot)
    update = {
        "message": {
            "text": f"{issued['command']}@ReportBot",
            "chat": {"id": -1004470066766, "type": "supergroup", "title": "Отчёты"},
        }
    }
    assert claim_telegram_bind_command(bot, update) == "-1004470066766"
    chats = get_workspace(bot)["telegram_report_chats"]
    assert chats[0]["chat_id"] == "-1004470066766"
    assert chats[0]["title"] == "Отчёты"
    assert get_workspace(bot)["telegram_report_bind"] is None


def test_set_command_works_for_basic_group_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Facade Metal-style group ids (-5381879266) must bind the same way as super-groups."""
    bot = _bot(monkeypatch)
    issued = issue_telegram_report_bind(bot)
    update = {
        "message": {
            "text": issued["command"],
            "chat": {"id": -5381879266, "type": "group", "title": "Тест"},
        }
    }
    assert claim_telegram_bind_command(bot, update) == "-5381879266"
    assert get_workspace(bot)["telegram_report_chats"][0]["chat_id"] == "-5381879266"


def test_wrong_set_command_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _bot(monkeypatch)
    issue_telegram_report_bind(bot)
    update = {
        "message": {
            "text": "/set_" + ("a" * 20),
            "chat": {"id": 7, "type": "private", "first_name": "Анна"},
        }
    }
    assert claim_telegram_bind_command(bot, update) is None
    assert get_workspace(bot)["telegram_report_chats"] == []


def test_expired_set_command_does_not_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _bot(monkeypatch)
    issued = issue_telegram_report_bind(bot)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    bot.credentials["_mpai_workspace"]["telegram_report_bind"]["expires_at"] = past
    update = {
        "message": {
            "text": issued["command"],
            "chat": {"id": 7, "type": "private", "first_name": "Анна"},
        }
    }
    assert claim_telegram_bind_command(bot, update) == ""
    assert get_workspace(bot)["telegram_report_chats"] == []


def test_private_chat_is_not_a_report_destination() -> None:
    update = {"message": {"chat": {"id": 12345, "type": "private", "first_name": "Анна"}}}
    assert apply_telegram_update_to_chats([], update) == []


def test_bot_removed_from_group_drops_the_chat() -> None:
    chats = [{"chat_id": "-1001", "title": "Telegram-чат", "connected_at": "t", "active": True}]
    update = {
        "my_chat_member": {
            "chat": {"id": -1001, "type": "supergroup", "title": "Telegram-чат"},
            "new_chat_member": {"status": "kicked", "user": {"is_bot": True}},
        }
    }
    assert apply_telegram_update_to_chats(chats, update) == []
