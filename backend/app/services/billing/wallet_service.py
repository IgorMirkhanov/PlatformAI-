"""Organization credit wallet — atomic deduct with row-level locking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db_integrity import is_unique_violation
from app.models.billing.credit_transaction import CreditTransaction
from app.models.billing.organization_wallet import OrganizationWallet
from app.repositories.billing.wallet_repository import wallet_repository


class InsufficientFundsError(RuntimeError):
    """Raised when the organization wallet cannot cover a debit."""

    def __init__(
        self,
        message: str = "Insufficient wallet balance.",
        *,
        organization_id: uuid.UUID | None = None,
        balance: int | None = None,
        required: int | None = None,
    ) -> None:
        super().__init__(message)
        self.organization_id = organization_id
        self.balance = balance
        self.required = required


class WalletNotFoundError(RuntimeError):
    """Raised when no wallet exists for the organization."""

    def __init__(self, organization_id: uuid.UUID) -> None:
        super().__init__(f"Wallet not found for organization '{organization_id}'.")
        self.organization_id = organization_id


class DuplicateTransactionError(RuntimeError):
    """Raised when a ledger insert violates the reference_id uniqueness guard."""

    def __init__(
        self,
        message: str = "Duplicate billing transaction reference.",
        *,
        reference_id: str | None = None,
        organization_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.reference_id = reference_id
        self.organization_id = organization_id


@dataclass(slots=True, frozen=True)
class DeductResult:
    organization_id: uuid.UUID
    amount: int
    balance_before: int
    balance_after: int
    transaction_id: uuid.UUID | None
    idempotent_replay: bool = False


class WalletService:
    """
    Tenant wallet mutations.

    Concurrent Celery / API workers must serialize on the wallet row via
    ``SELECT … FOR UPDATE`` so balance never goes negative under races.
    """

    async def get_or_create_wallet(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        initial_balance: int = 0,
    ) -> OrganizationWallet:
        repo = wallet_repository(db)
        existing = await repo.get(organization_id)
        if existing is not None:
            return existing
        wallet = OrganizationWallet(
            organization_id=organization_id,
            balance=int(initial_balance),
            balance_tokens=int(getattr(settings, "WALLET_LAUNCH_GRACE_TOKENS", 0) or 0)
            if initial_balance == 0
            else max(int(initial_balance), 0),
            status="active",
        )
        return await repo.add_wallet(wallet)

    async def get_balance(self, db: AsyncSession, organization_id: uuid.UUID) -> int:
        wallet = await wallet_repository(db).get(organization_id)
        if wallet is None:
            raise WalletNotFoundError(organization_id)
        return int(wallet.balance)

    async def deduct_credits(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        amount: int,
        tx_type: str,
        reference_id: str | None = None,
        *,
        auto_commit: bool = True,
    ) -> DeductResult:
        """
        Atomically debit ``amount`` credits from the org wallet.

        Steps (single DB transaction):
        1. Lock wallet row with ``SELECT … FOR UPDATE``.
        2. If ``reference_id`` is set, skip when a matching ledger row exists.
        3. Raise ``InsufficientFundsError`` when ``balance < amount``.
        4. Decrement balance, append negative ``CreditTransaction``, commit.
        """
        if amount <= 0:
            raise ValueError("amount must be a positive integer (credits to deduct).")
        tx_type_clean = (tx_type or "").strip()
        if not tx_type_clean:
            raise ValueError("tx_type is required.")
        ref = (reference_id or "").strip() or None

        repo = wallet_repository(db)
        wallet = await repo.get_for_update(organization_id)
        if wallet is None:
            raise WalletNotFoundError(organization_id)

        if ref is not None:
            existing = await repo.find_by_reference(
                wallet_id=organization_id,
                transaction_type=tx_type_clean,
                reference_id=ref,
            )
            if existing is not None:
                logger.info(
                    "Billing.wallet_deduct_idempotent | org={org} type={type} ref={ref}",
                    org=organization_id,
                    type=tx_type_clean,
                    ref=ref,
                )
                if auto_commit:
                    await db.commit()
                return DeductResult(
                    organization_id=organization_id,
                    amount=0,
                    balance_before=int(wallet.balance),
                    balance_after=int(wallet.balance),
                    transaction_id=existing.id,
                    idempotent_replay=True,
                )

        balance_before = int(wallet.balance)
        if balance_before < amount:
            logger.warning(
                "Billing.insufficient_funds | org={org} balance={bal} required={req}",
                org=organization_id,
                bal=balance_before,
                req=amount,
            )
            raise InsufficientFundsError(
                f"Insufficient funds: balance={balance_before}, required={amount} "
                f"(org={organization_id}).",
                organization_id=organization_id,
                balance=balance_before,
                required=amount,
            )

        wallet.balance = balance_before - amount
        txn = CreditTransaction(
            wallet_id=organization_id,
            amount=-amount,
            transaction_type=tx_type_clean,
            reference_id=ref,
        )
        try:
            async with db.begin_nested():
                await repo.add_transaction(txn)
            if auto_commit:
                await db.commit()
        except IntegrityError as exc:
            if auto_commit:
                await db.rollback()
            if ref is not None and is_unique_violation(exc):
                replay = await self._idempotent_replay(
                    db,
                    organization_id=organization_id,
                    transaction_type=tx_type_clean,
                    reference_id=ref,
                )
                if replay is not None:
                    return replay
            raise DuplicateTransactionError(
                f"Duplicate credit transaction reference '{ref}' (org={organization_id}).",
                reference_id=ref,
                organization_id=organization_id,
            ) from exc

        logger.info(
            "Billing.wallet_deducted | org={org} amount={amount} before={before} "
            "after={after} type={type} ref={ref} txn={txn}",
            org=organization_id,
            amount=amount,
            before=balance_before,
            after=wallet.balance,
            type=tx_type_clean,
            ref=ref,
            txn=txn.id,
        )
        return DeductResult(
            organization_id=organization_id,
            amount=amount,
            balance_before=balance_before,
            balance_after=int(wallet.balance),
            transaction_id=txn.id,
            idempotent_replay=False,
        )

    async def credit_credits(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        amount: int,
        tx_type: str,
        *,
        description: str | None = None,
        reference_id: str | None = None,
        invoice_id: uuid.UUID | None = None,
        auto_commit: bool = True,
    ) -> DeductResult:
        """Atomically credit the org wallet (positive ledger row)."""
        if amount <= 0:
            raise ValueError("amount must be a positive integer (credits to add).")
        tx_type_clean = (tx_type or "").strip()
        if not tx_type_clean:
            raise ValueError("tx_type is required.")
        ref = (reference_id or "").strip() or None

        repo = wallet_repository(db)
        wallet = await repo.get_for_update(organization_id)
        if wallet is None:
            wallet = await self.get_or_create_wallet(db, organization_id)
            wallet = await repo.get_for_update(organization_id)
        if wallet is None:
            raise WalletNotFoundError(organization_id)

        if ref is not None:
            existing = await repo.find_by_reference(
                wallet_id=organization_id,
                transaction_type=tx_type_clean,
                reference_id=ref,
            )
            if existing is not None:
                if auto_commit:
                    await db.commit()
                return DeductResult(
                    organization_id=organization_id,
                    amount=0,
                    balance_before=int(wallet.balance),
                    balance_after=int(wallet.balance),
                    transaction_id=existing.id,
                    idempotent_replay=True,
                )

        balance_before = int(wallet.balance)
        wallet.balance = balance_before + amount
        txn = CreditTransaction(
            wallet_id=organization_id,
            amount=amount,
            transaction_type=tx_type_clean,
            reference_id=ref,
            description=description,
            invoice_id=invoice_id,
        )
        try:
            # SAVEPOINT so unique-ref races do not abort an outer payment txn.
            async with db.begin_nested():
                await repo.add_transaction(txn)
            if auto_commit:
                await db.commit()
        except IntegrityError as exc:
            if auto_commit:
                await db.rollback()
            if ref is not None and is_unique_violation(exc):
                replay = await self._idempotent_replay(
                    db,
                    organization_id=organization_id,
                    transaction_type=tx_type_clean,
                    reference_id=ref,
                )
                if replay is not None:
                    # Outer payment txn may have already bumped balance; undo
                    # the speculative in-memory bump when we are nested.
                    if not auto_commit and int(wallet.balance) == balance_before + amount:
                        wallet.balance = balance_before
                    return replay
            raise DuplicateTransactionError(
                f"Duplicate credit transaction reference '{ref}' (org={organization_id}).",
                reference_id=ref,
                organization_id=organization_id,
            ) from exc

        logger.info(
            "Billing.wallet_credited | org={org} amount={amount} before={before} after={after} type={type}",
            org=organization_id,
            amount=amount,
            before=balance_before,
            after=wallet.balance,
            type=tx_type_clean,
        )
        return DeductResult(
            organization_id=organization_id,
            amount=amount,
            balance_before=balance_before,
            balance_after=int(wallet.balance),
            transaction_id=txn.id,
            idempotent_replay=False,
        )

    async def _idempotent_replay(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        transaction_type: str,
        reference_id: str,
    ) -> DeductResult | None:
        repo = wallet_repository(db)
        existing = await repo.find_by_reference(
            wallet_id=organization_id,
            transaction_type=transaction_type,
            reference_id=reference_id,
        )
        if existing is None:
            return None
        wallet = await repo.get(organization_id)
        balance = int(wallet.balance) if wallet is not None else 0
        logger.info(
            "Billing.wallet_deduct_idempotent_db | org={org} type={type} ref={ref}",
            org=organization_id,
            type=transaction_type,
            ref=reference_id,
        )
        return DeductResult(
            organization_id=organization_id,
            amount=0,
            balance_before=balance,
            balance_after=balance,
            transaction_id=existing.id,
            idempotent_replay=True,
        )


wallet_service = WalletService()
