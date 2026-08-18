"""Concurrency tests — organization wallet deduct under race conditions."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.billing.credit_transaction import CreditTransaction
from app.models.billing.organization_wallet import OrganizationWallet
from app.models.core_models import Company, UserRole
from app.models.users import User
from app.services.billing.wallet_service import InsufficientFundsError, wallet_service
async def _seed_wallet(
    factory: async_sessionmaker[AsyncSession],
    *,
    balance: int,
) -> uuid.UUID:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"wallet-race-{org_id.hex[:12]}@billing.test",
                hashed_password="!",
                company_name="Wallet Race Org",
                full_name="Wallet Tester",
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
                name="Wallet Race Org",
                owner_user_id=user_id,
                timezone="Asia/Almaty",
            )
        )
        await session.flush()
        session.add(
            OrganizationWallet(
                organization_id=org_id,
                balance=balance,
            )
        )
        await session.commit()
    return org_id


async def _cleanup_org(
    factory: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
) -> None:
    async with factory() as session:
        await session.execute(
            text("DELETE FROM credit_transactions WHERE wallet_id = :oid"),
            {"oid": org_id},
        )
        await session.execute(
            text("DELETE FROM organization_wallets WHERE organization_id = :oid"),
            {"oid": org_id},
        )
        await session.execute(
            text("DELETE FROM companies WHERE id = :oid"),
            {"oid": org_id},
        )
        await session.execute(
            text("DELETE FROM users WHERE company_id = :oid"),
            {"oid": org_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_concurrent_deduct_credits_never_overdraws(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """
    Wallet starts at 100. Five workers each try to deduct 30 concurrently.

    Exactly three must succeed (90), two must raise InsufficientFundsError,
    and the final balance must be exactly 10 — never negative.
    """
    org_id = await _seed_wallet(real_session_factory, balance=100)

    async def attempt_deduct() -> str:
        async with real_session_factory() as session:
            try:
                await wallet_service.deduct_credits(
                    session,
                    org_id,
                    30,
                    "llm_completion",
                    reference_id=None,
                )
                return "ok"
            except InsufficientFundsError:
                await session.rollback()
                return "insufficient"
            except Exception:
                await session.rollback()
                raise

    try:
        results = await asyncio.gather(*[attempt_deduct() for _ in range(5)])
        assert results.count("ok") == 3, results
        assert results.count("insufficient") == 2, results

        async with real_session_factory() as session:
            wallet = await session.scalar(
                select(OrganizationWallet).where(
                    OrganizationWallet.organization_id == org_id
                )
            )
            assert wallet is not None
            assert int(wallet.balance) == 10

            rows = (
                await session.scalars(
                    select(CreditTransaction).where(CreditTransaction.wallet_id == org_id)
                )
            ).all()
            assert len(rows) == 3
            assert sum(int(r.amount) for r in rows) == -90
            assert all(int(r.amount) == -30 for r in rows)
            assert all(r.transaction_type == "llm_completion" for r in rows)
    finally:
        await _cleanup_org(real_session_factory, org_id)


@pytest.mark.asyncio
async def test_deduct_credits_idempotent_on_reference_id(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_wallet(real_session_factory, balance=50)
    ref = f"celery-task-{uuid.uuid4()}"

    try:
        async with real_session_factory() as session:
            first = await wallet_service.deduct_credits(
                session,
                org_id,
                20,
                "webhook_dispatch",
                reference_id=ref,
            )
            assert first.idempotent_replay is False
            assert first.balance_after == 30

        async with real_session_factory() as session:
            second = await wallet_service.deduct_credits(
                session,
                org_id,
                20,
                "webhook_dispatch",
                reference_id=ref,
            )
            assert second.idempotent_replay is True
            assert second.balance_after == 30

        async with real_session_factory() as session:
            balance = await wallet_service.get_balance(session, org_id)
            assert balance == 30
            rows = (
                await session.scalars(
                    select(CreditTransaction).where(CreditTransaction.wallet_id == org_id)
                )
            ).all()
            assert len(rows) == 1
    finally:
        await _cleanup_org(real_session_factory, org_id)


@pytest.mark.asyncio
async def test_concurrent_deduct_same_reference_id_charges_once(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Five parallel debits with the same reference_id must charge exactly once."""
    org_id = await _seed_wallet(real_session_factory, balance=100)
    ref = f"parallel-ref-{uuid.uuid4()}"

    async def attempt_deduct() -> tuple[str, bool]:
        async with real_session_factory() as session:
            try:
                result = await wallet_service.deduct_credits(
                    session,
                    org_id,
                    20,
                    "llm_completion",
                    reference_id=ref,
                )
                return ("ok", result.idempotent_replay)
            except Exception:
                await session.rollback()
                raise

    try:
        results = await asyncio.gather(*[attempt_deduct() for _ in range(5)])
        assert all(status == "ok" for status, _ in results), results
        assert sum(1 for _, replay in results if not replay) == 1, results
        assert sum(1 for _, replay in results if replay) == 4, results

        async with real_session_factory() as session:
            balance = await wallet_service.get_balance(session, org_id)
            assert balance == 80
            rows = (
                await session.scalars(
                    select(CreditTransaction).where(
                        CreditTransaction.wallet_id == org_id,
                        CreditTransaction.reference_id == ref,
                    )
                )
            ).all()
            assert len(rows) == 1
            assert int(rows[0].amount) == -20
    finally:
        await _cleanup_org(real_session_factory, org_id)
