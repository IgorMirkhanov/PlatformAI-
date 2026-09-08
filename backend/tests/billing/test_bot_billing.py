"""Per-bot subscription and wallet helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.bot_billing_service import (
    BotSubscriptionInactiveError,
    is_subscription_active,
)


def test_inactive_flag_blocks_chat() -> None:
    bot = SimpleNamespace(subscription_active=False, subscription_expires_at=None)
    assert is_subscription_active(bot) is False


def test_active_flag_allows_chat() -> None:
    bot = SimpleNamespace(subscription_active=True, subscription_expires_at=None)
    assert is_subscription_active(bot) is True


def test_expired_subscription_blocks_chat() -> None:
    bot = SimpleNamespace(
        subscription_active=True,
        subscription_expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert is_subscription_active(bot) is False


def test_future_expiry_allows_chat() -> None:
    bot = SimpleNamespace(
        subscription_active=True,
        subscription_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    assert is_subscription_active(bot) is True


def test_ensure_subscription_raises() -> None:
    from app.services.bot_billing_service import bot_billing_service

    bot = SimpleNamespace(subscription_active=False, subscription_expires_at=None)
    try:
        bot_billing_service.ensure_subscription(bot)  # type: ignore[arg-type]
    except BotSubscriptionInactiveError as exc:
        assert "подписки" in str(exc)
    else:
        raise AssertionError("expected BotSubscriptionInactiveError")
