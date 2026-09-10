"""Per-bot subscription + credit wallet.

Chat / LLM replies require an active bot subscription. Prompts, functions,
channels and other settings stay editable without one. Spend is billed to
``bots.wallet_balance``, not the organization wallet.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core_models import Bot


SUBSCRIPTION_REQUIRED_MESSAGE = (
    "У этого агента нет активной подписки. Настройки доступны, ответы в мессенджерах отключены."
)


class BotSubscriptionInactiveError(RuntimeError):
    """Bot may be configured but must not answer in messengers."""

    def __init__(self, message: str = SUBSCRIPTION_REQUIRED_MESSAGE) -> None:
        super().__init__(message)
        self.code = "BOT_SUBSCRIPTION_INACTIVE"


class BotWalletInsufficientError(RuntimeError):
    """Bot-local credit wallet cannot cover the LLM request."""

    def __init__(self, message: str, *, balance: int = 0, required: int = 0) -> None:
        super().__init__(message)
        self.code = "INSUFFICIENT_FUNDS"
        self.balance = balance
        self.required = required


def trial_starter_credits() -> int:
    """Optional bot-wallet seed mirrored from register starter credits.

    Groq chat works at wallet_balance=0; this only helps paid models.
    Never reads or drains the organization wallet.
    """
    return max(0, int(getattr(settings, "REGISTER_WALLET_STARTER_CREDITS", 0) or 0))


def apply_auto_trial(bot: Bot) -> Bot:
    """Grant an open-ended trial so a newly created or cloned bot can chat."""
    bot.subscription_active = True
    bot.subscription_expires_at = None
    starter = trial_starter_credits()
    current = int(getattr(bot, "wallet_balance", 0) or 0)
    if starter > 0 and current <= 0:
        bot.wallet_balance = starter
    return bot


def is_subscription_active(bot: Any, *, now: datetime | None = None) -> bool:
    if bot is None or not bool(getattr(bot, "subscription_active", False)):
        return False
    expires = getattr(bot, "subscription_expires_at", None)
    if expires is None:
        return True
    stamp = expires if expires.tzinfo is not None else expires.replace(tzinfo=UTC)
    return stamp > (now or datetime.now(UTC))


class BotBillingService:
    async def get_bot(self, db: AsyncSession, bot_id: uuid.UUID, *, for_update: bool = False) -> Bot | None:
        stmt = select(Bot).where(Bot.id == bot_id, Bot.deleted_at.is_(None))
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    def ensure_subscription(self, bot: Bot | None) -> Bot:
        if bot is None:
            raise BotSubscriptionInactiveError("Agent not found.")
        if not is_subscription_active(bot):
            raise BotSubscriptionInactiveError(SUBSCRIPTION_REQUIRED_MESSAGE)
        return bot

    async def ensure_chat_allowed(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        required_credits: int = 0,
    ) -> Bot:
        bot = await self.get_bot(db, bot_id)
        self.ensure_subscription(bot)
        needed = max(0, int(required_credits))
        if needed <= 0:
            return bot
        balance = int(getattr(bot, "wallet_balance", 0) or 0)
        if balance < needed:
            raise BotWalletInsufficientError(
                (getattr(bot, "low_balance_message", None) or "").strip()
                or "Баланс агента исчерпан. Пополните баланс бота, чтобы возобновить ответы.",
                balance=balance,
                required=needed,
            )
        return bot

    async def debit_credits(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        amount: int,
        *,
        reference_id: str | None = None,
    ) -> dict[str, Any]:
        if amount <= 0:
            bot = await self.get_bot(db, bot_id)
            return {
                "credits": 0,
                "skipped": "zero_cost",
                "balance_after": int(getattr(bot, "wallet_balance", 0) or 0) if bot else 0,
                "reference_id": reference_id,
            }
        bot = await self.get_bot(db, bot_id, for_update=True)
        self.ensure_subscription(bot)
        before = int(bot.wallet_balance or 0)
        if before < amount:
            raise BotWalletInsufficientError(
                (bot.low_balance_message or "").strip()
                or "Баланс агента исчерпан. Пополните баланс бота, чтобы возобновить ответы.",
                balance=before,
                required=amount,
            )
        bot.wallet_balance = before - amount
        await db.flush()
        logger.info(
            "BotBilling.debit | bot={bot} amount={amount} before={before} after={after} ref={ref}",
            bot=bot_id,
            amount=amount,
            before=before,
            after=bot.wallet_balance,
            ref=reference_id or "-",
        )
        return {
            "credits": amount,
            "balance_before": before,
            "balance_after": int(bot.wallet_balance),
            "reference_id": reference_id,
            "idempotent_replay": False,
        }

    async def adjust_balance(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        amount_delta: int,
    ) -> dict[str, Any]:
        if amount_delta == 0:
            raise ValueError("amount_delta must be non-zero.")
        bot = await self.get_bot(db, bot_id, for_update=True)
        if bot is None:
            raise LookupError("Bot not found.")
        before = int(bot.wallet_balance or 0)
        after = before + int(amount_delta)
        if after < 0:
            raise BotWalletInsufficientError(
                f"Balance cannot go negative (current={before}, delta={amount_delta}).",
                balance=before,
                required=abs(int(amount_delta)),
            )
        bot.wallet_balance = after
        await db.flush()
        return {
            "bot_id": bot.id,
            "previous_balance": before,
            "amount_delta": int(amount_delta),
            "new_balance": after,
        }

    async def set_subscription(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        active: bool,
        expires_at: datetime | None = None,
    ) -> Bot:
        bot = await self.get_bot(db, bot_id, for_update=True)
        if bot is None:
            raise LookupError("Bot not found.")
        bot.subscription_active = bool(active)
        bot.subscription_expires_at = expires_at
        await db.flush()
        return bot


bot_billing_service = BotBillingService()
