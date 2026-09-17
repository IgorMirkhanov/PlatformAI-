"""Unit tests for bot Control-tab config normalization."""

from __future__ import annotations

from app.services.bot_control_config import (
    normalize_control_config,
    phrase_matches,
)


def test_normalize_control_config_defaults() -> None:
    cfg = normalize_control_config(None)
    assert cfg["history"]["message_limit"] == 20
    assert cfg["history"]["time_window_days"] == 7
    assert cfg["spam_protection"]["enabled"] is False
    assert cfg["operator_intervention"]["pause_on_operator_message"] is True
    assert cfg["keyword_dialog"]["stop_phrases"] == []


def test_normalize_control_config_clamps_and_lists() -> None:
    cfg = normalize_control_config(
        {
            "history": {"message_limit": 999, "time_window_days": 0},
            "keyword_dialog": {
                "stop_enabled": True,
                "stop_phrases": ["  Stop ", "stop", "", "Вызови менеджера"],
            },
        }
    )
    assert cfg["history"]["message_limit"] == 200
    assert cfg["history"]["time_window_days"] == 1
    assert cfg["keyword_dialog"]["stop_phrases"] == ["Stop", "Вызови менеджера"]


def test_phrase_matches_substring_case_insensitive() -> None:
    assert phrase_matches("Хочу оператора пожалуйста", ["оператор"])
    assert not phrase_matches("привет", ["оператор"])
