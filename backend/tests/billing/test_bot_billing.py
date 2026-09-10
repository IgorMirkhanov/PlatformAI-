"""Per-bot subscription and wallet helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.bot_billing_service import (
    BotSubscriptionInactiveError,
    apply_auto_trial,
    is_subscription_active,
    trial_starter_credits,
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


def test_apply_auto_trial_enables_open_ended_subscription() -> None:
    bot = SimpleNamespace(subscription_active=False, subscription_expires_at=None, wallet_balance=0)
    apply_auto_trial(bot)  # type: ignore[arg-type]
    assert bot.subscription_active is True
    assert bot.subscription_expires_at is None


def test_apply_auto_trial_mirrors_starter_credits(monkeypatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "REGISTER_WALLET_STARTER_CREDITS", 250)
    bot = SimpleNamespace(subscription_active=False, subscription_expires_at=None, wallet_balance=0)
    apply_auto_trial(bot)  # type: ignore[arg-type]
    assert bot.subscription_active is True
    assert bot.wallet_balance == 250
    assert trial_starter_credits() == 250


def test_apply_auto_trial_does_not_overwrite_existing_wallet(monkeypatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "REGISTER_WALLET_STARTER_CREDITS", 250)
    bot = SimpleNamespace(subscription_active=False, subscription_expires_at=None, wallet_balance=10)
    apply_auto_trial(bot)  # type: ignore[arg-type]
    assert bot.wallet_balance == 10


def test_ensure_subscription_raises() -> None:
    from app.services.bot_billing_service import bot_billing_service

    bot = SimpleNamespace(subscription_active=False, subscription_expires_at=None)
    try:
        bot_billing_service.ensure_subscription(bot)  # type: ignore[arg-type]
    except BotSubscriptionInactiveError as exc:
        assert "подписки" in str(exc)
    else:
        raise AssertionError("expected BotSubscriptionInactiveError")
