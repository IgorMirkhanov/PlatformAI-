"""Billing wallet data access — row-locked reads and ledger inserts."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing.credit_transaction import CreditTransaction
from app.models.billing.organization_wallet import OrganizationWallet


class WalletRepository:
    """Low-level wallet / ledger queries (always org-scoped via wallet PK)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_update(self, organization_id: uuid.UUID) -> OrganizationWallet | None:
        """``SELECT … FOR UPDATE`` — serializes concurrent balance mutations."""
        result = await self.session.execute(
            select(OrganizationWallet)
            .where(OrganizationWallet.organization_id == organization_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get(self, organization_id: uuid.UUID) -> OrganizationWallet | None:
        return await self.session.get(OrganizationWallet, organization_id)

    async def add_wallet(self, wallet: OrganizationWallet) -> OrganizationWallet:
        self.session.add(wallet)
        await self.session.flush()
        return wallet

    async def find_by_reference(
        self,
        *,
        wallet_id: uuid.UUID,
        transaction_type: str,
        reference_id: str,
    ) -> CreditTransaction | None:
        result = await self.session.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.wallet_id == wallet_id,
                CreditTransaction.transaction_type == transaction_type,
                CreditTransaction.reference_id == reference_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add_transaction(self, txn: CreditTransaction) -> CreditTransaction:
        self.session.add(txn)
        await self.session.flush()
        return txn


def wallet_repository(session: AsyncSession) -> WalletRepository:
    return WalletRepository(session)
