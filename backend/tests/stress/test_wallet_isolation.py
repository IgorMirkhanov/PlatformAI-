"""Cross-tenant wallet isolation under concurrent debit_atomic."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.billing.organization_wallet import OrganizationWallet
from app.models.core_models import Company, UserRole
from app.models.users import User
from app.models.wallet import WalletTransaction, WalletTxType
from app.repositories.wallet_repository import wallet_repository


async def _seed(
    factory: async_sessionmaker[AsyncSession],
    *,
    tokens: int,
) -> uuid.UUID:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"iso-{org_id.hex[:12]}@wallet.test",
                hashed_password="!",
                company_name="Iso Org",
                full_name="Iso Tester",
                company_id=org_id,
                role=UserRole.OWNER,
                is_superadmin=False,
                timezone="Asia/Almaty",
            )
        )
        await session.flush()
        session.add(Company(id=org_id, name="Iso Org", owner_user_id=user_id, timezone="Asia/Almaty"))
        await session.flush()
        session.add(
            OrganizationWallet(
                organization_id=org_id,
                balance=0,
                balance_tokens=tokens,
                status="active",
            )
        )
        await session.commit()
    return org_id


@pytest.mark.asyncio
async def test_fifty_debits_ten_succeed_and_org_b_unaffected(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_a = await _seed(real_session_factory, tokens=10)
    org_b = await _seed(real_session_factory, tokens=10_000)

    async def debit(org_id: uuid.UUID, key: str) -> tuple[bool, float]:
        started = time.perf_counter()
        async with real_session_factory() as session:
            result = await wallet_repository(session).debit_atomic(org_id, 1, key)
            if result.success and not result.idempotent_replay:
                await session.commit()
            else:
                await session.rollback()
        return result.success and not result.idempotent_replay, (time.perf_counter() - started) * 1000

    a_tasks = [debit(org_a, f"a:{i}") for i in range(50)]
    b_tasks = [debit(org_b, f"b:{i}") for i in range(20)]
    a_results, b_results = await asyncio.gather(
        asyncio.gather(*a_tasks),
        asyncio.gather(*b_tasks),
    )

    assert sum(1 for ok, _ in a_results if ok) == 10
    assert all(ok for ok, _ in b_results)

    async with real_session_factory() as session:
        wallet_a = await wallet_repository(session).get_by_org(org_a)
        wallet_b = await wallet_repository(session).get_by_org(org_b)
        debit_count = await session.scalar(
            select(func.count())
            .select_from(WalletTransaction)
            .where(
                WalletTransaction.organization_id == org_a,
                WalletTransaction.tx_type == WalletTxType.DEBIT_AI_USAGE.value,
            )
        )
        db_balance = int(wallet_a.balance_tokens) if wallet_a is not None else -1
    assert wallet_a is not None
    assert db_balance >= 0
    assert db_balance == 0
    assert int(debit_count or 0) == 10
    assert wallet_a.status == "blocked"
    assert wallet_b is not None and int(wallet_b.balance_tokens) == 10_000 - 20
    assert int(wallet_a.balance_tokens) >= 0

    b_latencies = sorted(ms for _, ms in b_results)
    p95 = b_latencies[int(len(b_latencies) * 0.95) - 1]
    # Production SLO is 200ms; Windows Docker testcontainers is often multi-second.
    # This bound only guards a hang, not the commercial latency target.
    budget_ms = 8_000 if sys.platform == "win32" else 750
    assert p95 < budget_ms, f"org B p95={p95:.1f}ms under org A load (budget={budget_ms})"
