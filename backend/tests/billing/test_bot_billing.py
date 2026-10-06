"""Per-bot subscription and wallet helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_top_up_moves_org_tenge_onto_bot(monkeypatch) -> None:
    import uuid
    from decimal import Decimal

    from app.services.bot_billing_service import bot_billing_service
    from app.services.wallet_service import WalletDeductionResult

    bot_id = uuid.uuid4()
    org_id = uuid.uuid4()
    bot = SimpleNamespace(id=bot_id, name="RKR", organization_id=org_id, wallet_balance=0)

    async def get_bot(_db, _bot_id, for_update=False):
        return bot

    async def adjust_balance(_db, _bot_id, delta):
        before = bot.wallet_balance
        bot.wallet_balance += delta
        return {
            "previous_balance": before,
            "new_balance": bot.wallet_balance,
            "amount_delta": delta,
        }

    seen: dict[str, object] = {}

    async def deduct_wallet(_db, org, amount, **kwargs):
        seen["kzt"] = amount
        seen["description"] = kwargs["description"]
        return WalletDeductionResult(
            org_id=org,
            user_id=uuid.uuid4(),
            subscription_id=uuid.uuid4(),
            amount_kzt=Decimal(amount),
            balance_before=Decimal("5000.00"),
            balance_after=Decimal("4000.00"),
        )

    class Mirror:
        balance = 5000

    class Repo:
        async def get(self, _organization_id):
            return Mirror()

    async def deduct_credits(_db, _organization_id, amount, _tx_type, reference_id=None, auto_commit=True):
        seen["credits"] = amount
        seen["auto_commit"] = auto_commit
        return None

    import importlib

    wallet_repo_mod = importlib.import_module("app.repositories.billing.wallet_repository")
    credit_wallet_mod = importlib.import_module("app.services.billing.wallet_service")
    org_wallet_mod = importlib.import_module("app.services.wallet_service")

    monkeypatch.setattr(bot_billing_service, "get_bot", get_bot)
    monkeypatch.setattr(bot_billing_service, "adjust_balance", adjust_balance)
    monkeypatch.setattr(org_wallet_mod.wallet_service, "deduct_wallet_balance", deduct_wallet)
    monkeypatch.setattr(wallet_repo_mod, "wallet_repository", lambda _db: Repo())
    monkeypatch.setattr(credit_wallet_mod.wallet_service, "deduct_credits", deduct_credits)

    result = await bot_billing_service.top_up_from_organization(None, bot_id, org_id, 1000)  # type: ignore[arg-type]

    assert result["bot_balance"] == 1000
    assert result["organization_balance"] == 4000.0
    assert seen["kzt"] == 1000
    assert seen["credits"] == 1000
    assert seen["auto_commit"] is False
    assert "RKR" in str(seen["description"])


def test_ensure_subscription_raises() -> None:
    from app.services.bot_billing_service import bot_billing_service

    bot = SimpleNamespace(subscription_active=False, subscription_expires_at=None)
    try:
        bot_billing_service.ensure_subscription(bot)  # type: ignore[arg-type]
    except BotSubscriptionInactiveError as exc:
        assert "подписки" in str(exc)
    else:
        raise AssertionError("expected BotSubscriptionInactiveError")
