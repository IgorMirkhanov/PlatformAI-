"""Follow-up message extras + schedule helpers."""

from __future__ import annotations

from app.services.bot_message_extras import (
    follow_up_delay_seconds,
    normalize_message_extras,
)
from app.tasks.follow_up_task import seconds_until_next_schedule_window


def test_normalize_legacy_total_hours() -> None:
    extras = normalize_message_extras({"follow_up_enabled": True, "follow_up_delay_hours": 24})
    assert extras["follow_up_delay_days"] == 1
    assert extras["follow_up_delay_hours"] == 0
    assert extras["follow_up_delay_minutes"] == 0
    assert follow_up_delay_seconds(extras) == 86400


def test_normalize_dhm() -> None:
    extras = normalize_message_extras(
        {
            "follow_up_enabled": True,
            "follow_up_delay_days": 0,
            "follow_up_delay_hours": 4,
            "follow_up_delay_minutes": 30,
            "follow_up_send_count": 2,
            "follow_up_frequency": "once_per_dialogue",
            "follow_up_instructions": "Напомни про расчёт",
            "follow_up_off_hours_mode": "send_anyway",
        }
    )
    assert extras["follow_up_delay_hours"] == 4
    assert extras["follow_up_delay_minutes"] == 30
    assert extras["follow_up_send_count"] == 2
    assert extras["follow_up_instructions"] == "Напомни про расчёт"
    assert follow_up_delay_seconds(extras) == 4 * 3600 + 30 * 60


def test_delay_minimum_one_minute() -> None:
    extras = normalize_message_extras(
        {
            "follow_up_delay_days": 0,
            "follow_up_delay_hours": 0,
            "follow_up_delay_minutes": 0,
        }
    )
    assert follow_up_delay_seconds(extras) >= 60


def test_schedule_disabled_means_always_open() -> None:
    assert seconds_until_next_schedule_window({"enabled": False}) is None
    assert seconds_until_next_schedule_window({"enabled": True, "windows": []}) is None
