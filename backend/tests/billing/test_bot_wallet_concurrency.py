"""Concurrency tests — per-bot wallet debit under race conditions.

Reproduces the lifecycle stress failure mode: the same request session loads
the Bot row (``ensure_chat_allowed``) before the LLM call, then debit must
still see commits from sibling sessions — not a stale identity-map balance.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.core_models import Bot, Company, PlatformType, UserRole
from app.models.users import User
from app.services.bot_billing_service import (
    BotWalletInsufficientError,
    bot_billing_service,
)


async def _seed_bot(
    factory: async_sessionmaker[AsyncSession],
    *,
    balance: int,
) -> uuid.UUID:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"bot-wallet-race-{org_id.hex[:12]}@billing.test",
                hashed_password="!",
                company_name="Bot Wallet Race",
                full_name="Bot Wallet Tester",
                company_id=org_id,
                role=UserRole.OWNER,
                is_superadmin=False,
                timezone="Asia/Almaty",
            )
        )
        await session.flush()
        session.add(
            Company(
                id=org_id,
                name="Bot Wallet Race",
                owner_user_id=user_id,
                timezone="Asia/Almaty",
            )
        )
        await session.flush()
        session.add(
            Bot(
                id=bot_id,
                user_id=user_id,
                organization_id=org_id,
                name="Race Bot",
                platform_type=PlatformType.TELEGRAM,
                is_active=True,
                subscription_active=True,
                wallet_balance=balance,
            )
        )
        await session.commit()
    return bot_id


async def _cleanup_bot(
    factory: async_sessionmaker[AsyncSession],
    bot_id: uuid.UUID,
) -> None:
    async with factory() as session:
        bot = await session.get(Bot, bot_id)
        if bot is None:
            return
        org_id = bot.organization_id
        user_id = bot.user_id
        await session.execute(text("DELETE FROM bots WHERE id = :id"), {"id": bot_id})
        if org_id is not None:
            await session.execute(
                text("DELETE FROM companies WHERE id = :id"), {"id": org_id}
            )
        await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await session.commit()


@pytest.mark.asyncio
async def test_concurrent_bot_debit_never_loses_updates(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """
    Bot starts at 100. Thirty workers each debit 1 after a pre-load (simulating
    ``ensure_chat_allowed`` before the LLM call).

    Final balance must be exactly 70 — never a lost-update residual near 99.
    """
    bot_id = await _seed_bot(real_session_factory, balance=100)
    workers = 30
    debit_each = 1

    async def attempt_debit() -> str:
        async with real_session_factory() as session:
            # Mimic orchestrator: load bot into identity map BEFORE debit.
            await bot_billing_service.ensure_chat_allowed(
                session, bot_id, required_credits=debit_each
            )
            # Yield so sibling tasks also pre-load the same starting balance.
            await asyncio.sleep(0)
            try:
                await bot_billing_service.debit_credits(
                    session, bot_id, debit_each, reference_id=str(uuid.uuid4())
                )
                await session.commit()
                return "ok"
            except BotWalletInsufficientError:
                await session.rollback()
                return "insufficient"

    try:
        outcomes = await asyncio.gather(*[attempt_debit() for _ in range(workers)])
        assert outcomes.count("ok") == workers
        assert outcomes.count("insufficient") == 0

        async with real_session_factory() as session:
            balance = int(
                (
                    await session.execute(
                        select(Bot.wallet_balance).where(Bot.id == bot_id)
                    )
                ).scalar_one()
            )
        assert balance == 100 - workers * debit_each
    finally:
        await _cleanup_bot(real_session_factory, bot_id)


@pytest.mark.asyncio
async def test_concurrent_bot_debit_never_overdraws(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Wallet=100, five workers debit 30 → exactly three succeed, balance=10."""
    bot_id = await _seed_bot(real_session_factory, balance=100)

    async def attempt_debit() -> str:
        async with real_session_factory() as session:
            await bot_billing_service.ensure_chat_allowed(session, bot_id, required_credits=1)
            await asyncio.sleep(0)
            try:
                await bot_billing_service.debit_credits(session, bot_id, 30)
                await session.commit()
                return "ok"
            except BotWalletInsufficientError:
                await session.rollback()
                return "insufficient"

    try:
        outcomes = await asyncio.gather(*[attempt_debit() for _ in range(5)])
        assert outcomes.count("ok") == 3
        assert outcomes.count("insufficient") == 2

        async with real_session_factory() as session:
            balance = int(
                (
                    await session.execute(
                        select(Bot.wallet_balance).where(Bot.id == bot_id)
                    )
                ).scalar_one()
            )
        assert balance == 10
    finally:
        await _cleanup_bot(real_session_factory, bot_id)
