"""Token wallet repository — org-scoped row locks, never a global lock.

``SELECT … FOR UPDATE`` targets only ``organization_wallets`` where
``organization_id = :org_id``. PostgreSQL row-level locks are per tuple;
org B's wallet row cannot be blocked by a lock held on org A's row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing.organization_wallet import OrganizationWallet
from app.models.wallet import DEBIT_TX_TYPES, WalletStatus, WalletTransaction, WalletTxType


@dataclass(slots=True)
class WalletDebitResult:
    success: bool
    reason: str | None = None
    balance_after: int = 0
    transaction_id: uuid.UUID | None = None
    idempotent_replay: bool = False


class WalletRepository:
    """Ledger mutations. Callers own the AsyncSession / unit-of-work."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_org(self, org_id: uuid.UUID) -> OrganizationWallet | None:
        """Non-locking read — used for pre-generation checks."""
        return await self.session.get(OrganizationWallet, org_id)

    async def get_for_update(self, org_id: uuid.UUID) -> OrganizationWallet | None:
        result = await self.session.execute(
            select(OrganizationWallet)
            .where(OrganizationWallet.organization_id == org_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def debit_atomic(
        self,
        org_id: uuid.UUID,
        amount_tokens: int,
        idempotency_key: str,
        *,
        bot_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        model_used: str | None = None,
        tx_type: str = WalletTxType.DEBIT_AI_USAGE.value,
        metadata: dict[str, Any] | None = None,
    ) -> WalletDebitResult:
        if amount_tokens <= 0:
            raise ValueError("amount_tokens must be positive")
        key = (idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotency_key is required")
        if tx_type not in DEBIT_TX_TYPES:
            raise ValueError(f"tx_type {tx_type!r} is not a debit type")

        wallet = await self.get_for_update(org_id)
        if wallet is None:
            return WalletDebitResult(success=False, reason="wallet_not_found")

        existing = await self._find_by_idempotency(org_id, key)
        if existing is not None:
            return WalletDebitResult(
                success=True,
                reason="idempotent_replay",
                balance_after=int(wallet.balance_tokens),
                transaction_id=existing.id,
                idempotent_replay=True,
            )

        if wallet.status == WalletStatus.BLOCKED.value or int(wallet.balance_tokens) < amount_tokens:
            return WalletDebitResult(
                success=False,
                reason="insufficient_balance",
                balance_after=int(wallet.balance_tokens),
            )

        new_balance = int(wallet.balance_tokens) - amount_tokens
        now = datetime.now(timezone.utc)
        tx_id = uuid.uuid4()
        stmt = (
            pg_insert(WalletTransaction)
            .values(
                id=tx_id,
                organization_id=org_id,
                wallet_id=org_id,
                bot_id=bot_id,
                conversation_id=conversation_id,
                tx_type=tx_type,
                amount_tokens=amount_tokens,
                balance_after=new_balance,
                model_used=(model_used or None),
                idempotency_key=key,
                metadata_json=metadata or {},
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "idempotency_key"])
            .returning(WalletTransaction.id)
        )
        inserted_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if inserted_id is None:
            replay = await self._find_by_idempotency(org_id, key)
            return WalletDebitResult(
                success=True,
                reason="idempotent_replay",
                balance_after=int(wallet.balance_tokens),
                transaction_id=replay.id if replay is not None else None,
                idempotent_replay=True,
            )

        blocked = new_balance <= 0
        await self.session.execute(
            update(OrganizationWallet)
            .where(OrganizationWallet.organization_id == org_id)
            .values(
                balance_tokens=new_balance,
                version=OrganizationWallet.version + 1,
                updated_at=now,
                status=WalletStatus.BLOCKED.value if blocked else OrganizationWallet.status,
                blocked_at=now if blocked else OrganizationWallet.blocked_at,
            )
        )
        wallet.balance_tokens = new_balance
        wallet.version = int(wallet.version) + 1
        if blocked:
            wallet.status = WalletStatus.BLOCKED.value
            wallet.blocked_at = now
        await self.session.flush()
        return WalletDebitResult(
            success=True,
            reason="ok",
            balance_after=new_balance,
            transaction_id=inserted_id,
        )

    async def credit_atomic(
        self,
        org_id: uuid.UUID,
        amount_tokens: int,
        tx_type: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> WalletDebitResult:
        if amount_tokens <= 0:
            raise ValueError("amount_tokens must be positive")
        key = (idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotency_key is required")
        if tx_type in DEBIT_TX_TYPES:
            raise ValueError(f"tx_type {tx_type!r} is a debit type")

        wallet = await self.get_for_update(org_id)
        if wallet is None:
            wallet = OrganizationWallet(
                organization_id=org_id,
                balance=0,
                balance_tokens=0,
                status=WalletStatus.ACTIVE.value,
            )
            self.session.add(wallet)
            await self.session.flush()
            wallet = await self.get_for_update(org_id)
        if wallet is None:
            return WalletDebitResult(success=False, reason="wallet_not_found")

        existing = await self._find_by_idempotency(org_id, key)
        if existing is not None:
            return WalletDebitResult(
                success=True,
                reason="idempotent_replay",
                balance_after=int(wallet.balance_tokens),
                transaction_id=existing.id,
                idempotent_replay=True,
            )

        new_balance = int(wallet.balance_tokens) + amount_tokens
        now = datetime.now(timezone.utc)
        tx_id = uuid.uuid4()
        stmt = (
            pg_insert(WalletTransaction)
            .values(
                id=tx_id,
                organization_id=org_id,
                wallet_id=org_id,
                tx_type=tx_type,
                amount_tokens=amount_tokens,
                balance_after=new_balance,
                idempotency_key=key,
                metadata_json=metadata or {},
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "idempotency_key"])
            .returning(WalletTransaction.id)
        )
        inserted_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if inserted_id is None:
            replay = await self._find_by_idempotency(org_id, key)
            return WalletDebitResult(
                success=True,
                reason="idempotent_replay",
                balance_after=int(wallet.balance_tokens),
                transaction_id=replay.id if replay is not None else None,
                idempotent_replay=True,
            )

        await self.session.execute(
            update(OrganizationWallet)
            .where(OrganizationWallet.organization_id == org_id)
            .values(
                balance_tokens=new_balance,
                version=OrganizationWallet.version + 1,
                updated_at=now,
                status=WalletStatus.ACTIVE.value,
                blocked_at=None,
            )
        )
        wallet.balance_tokens = new_balance
        wallet.version = int(wallet.version) + 1
        wallet.status = WalletStatus.ACTIVE.value
        wallet.blocked_at = None
        await self.session.flush()
        return WalletDebitResult(
            success=True,
            reason="ok",
            balance_after=new_balance,
            transaction_id=inserted_id,
        )

    async def list_recent(
        self,
        org_id: uuid.UUID,
        *,
        limit: int = 20,
    ) -> list[WalletTransaction]:
        stmt = (
            select(WalletTransaction)
            .where(WalletTransaction.organization_id == org_id)
            .order_by(WalletTransaction.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        return list((await self.session.scalars(stmt)).all())

    async def usage_by_bot(
        self,
        org_id: uuid.UUID,
        *,
        days: int = 7,
    ) -> list[tuple[uuid.UUID | None, int]]:
        since = datetime.now(timezone.utc) - timedelta(days=int(max(1, min(days, 365))))
        stmt = (
            select(
                WalletTransaction.bot_id,
                func.coalesce(func.sum(WalletTransaction.amount_tokens), 0),
            )
            .where(
                WalletTransaction.organization_id == org_id,
                WalletTransaction.tx_type.in_(list(DEBIT_TX_TYPES)),
                WalletTransaction.created_at >= since,
            )
            .group_by(WalletTransaction.bot_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], int(row[1] or 0)) for row in rows]

    async def _find_by_idempotency(
        self, org_id: uuid.UUID, idempotency_key: str
    ) -> WalletTransaction | None:
        result = await self.session.execute(
            select(WalletTransaction)
            .where(
                WalletTransaction.organization_id == org_id,
                WalletTransaction.idempotency_key == idempotency_key,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


def wallet_repository(session: AsyncSession) -> WalletRepository:
    return WalletRepository(session)
