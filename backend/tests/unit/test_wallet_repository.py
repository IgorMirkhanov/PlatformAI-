"""Token wallet debit/credit unit tests against real Postgres."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.billing.organization_wallet import OrganizationWallet
from app.models.core_models import Company, UserRole
from app.models.users import User
from app.models.wallet import WalletTxType
from app.repositories.wallet_repository import wallet_repository


async def _seed_org(
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
                email=f"token-{org_id.hex[:12]}@wallet.test",
                hashed_password="!",
                company_name="Token Org",
                full_name="Token Tester",
                company_id=org_id,
                role=UserRole.OWNER,
                is_superadmin=False,
                timezone="Asia/Almaty",
            )
        )
        await session.flush()
        session.add(Company(id=org_id, name="Token Org", owner_user_id=user_id, timezone="Asia/Almaty"))
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
async def test_debit_atomic_idempotent_key_does_not_double_charge(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(real_session_factory, tokens=100)
    async with real_session_factory() as session:
        repo = wallet_repository(session)
        first = await repo.debit_atomic(org_id, 10, "conv:msg-1")
        second = await repo.debit_atomic(org_id, 10, "conv:msg-1")
        await session.commit()
        wallet = await repo.get_by_org(org_id)
    assert first.success and not first.idempotent_replay
    assert second.success and second.idempotent_replay
    assert wallet is not None
    assert int(wallet.balance_tokens) == 90


@pytest.mark.asyncio
async def test_debit_atomic_insufficient_does_not_change_balance(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(real_session_factory, tokens=5)
    async with real_session_factory() as session:
        repo = wallet_repository(session)
        result = await repo.debit_atomic(org_id, 9, "conv:msg-2")
        await session.rollback()
        wallet = await repo.get_by_org(org_id)
    assert result.success is False
    assert result.reason == "insufficient_balance"
    assert wallet is not None
    assert int(wallet.balance_tokens) == 5


@pytest.mark.asyncio
async def test_credit_atomic_idempotent_topup(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(real_session_factory, tokens=1)
    async with real_session_factory() as session:
        repo = wallet_repository(session)
        first = await repo.credit_atomic(
            org_id, 50, WalletTxType.CREDIT_TOPUP.value, "payment:stripe:evt_1"
        )
        second = await repo.credit_atomic(
            org_id, 50, WalletTxType.CREDIT_TOPUP.value, "payment:stripe:evt_1"
        )
        await session.commit()
        wallet = await repo.get_by_org(org_id)
    assert first.success and not first.idempotent_replay
    assert second.idempotent_replay
    assert int(wallet.balance_tokens) == 51
