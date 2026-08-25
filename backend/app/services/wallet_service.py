"""Atomic org wallet debit/credit with row-level locking.

Wallet balance lives on the org owner's ``Subscription`` row until a dedicated
org ledger ships. Concurrent Celery workers must serialize on that row via
``SELECT … FOR UPDATE``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_integrity import is_unique_violation

from app.models.core_models import (
    BillingTransaction,
    BillingTransactionStatus,
    BillingTransactionType,
    DiagnosticErrorType,
    Organization,
    Subscription,
    SubscriptionStatus,
)
from app.core.pg_locks import LOCK_NS_WALLET, pg_advisory_xact_lock_uuid
from app.services.diagnostic_log_service import diagnostic_log_service


class InsufficientFundsException(RuntimeError):
    """Raised when the wallet cannot cover the requested debit."""

    def __init__(
        self,
        message: str = "Insufficient wallet balance.",
        *,
        org_id: uuid.UUID | None = None,
        balance: Decimal | None = None,
        required: Decimal | None = None,
    ) -> None:
        super().__init__(message)
        self.org_id = org_id
        self.balance = balance
        self.required = required


# Alias for callers that prefer the shorter name used in AI orchestration.
InsufficientFundsError = InsufficientFundsException


class DuplicateTransactionError(RuntimeError):
    """Raised when a billing ledger row violates reference_id uniqueness."""

    def __init__(
        self,
        message: str = "Duplicate billing transaction reference.",
        *,
        reference_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reference_id = reference_id

# ~$5 USD at platform FX (~500 KZT/USD) — warn when wallet is below this.
DEFAULT_LOW_BALANCE_THRESHOLD_KZT = Decimal("2500.00")


@dataclass(slots=True)
class WalletDeductionResult:
    org_id: uuid.UUID
    user_id: uuid.UUID
    subscription_id: uuid.UUID
    amount_kzt: Decimal
    balance_before: Decimal
    balance_after: Decimal
    transaction_id: uuid.UUID | None = None


class WalletService:
    """Thread-safe wallet mutations for multi-worker Celery environments."""

    def __init__(self, *, low_balance_threshold_kzt: Decimal | float | None = None) -> None:
        from app.core.config import settings

        configured = getattr(settings, "LOW_BALANCE_THRESHOLD_KZT", None)
        raw = low_balance_threshold_kzt if low_balance_threshold_kzt is not None else configured
        self.low_balance_threshold = Decimal(
            str(raw if raw is not None else DEFAULT_LOW_BALANCE_THRESHOLD_KZT)
        )

    @staticmethod
    def _as_uuid(org_id: uuid.UUID | str | int) -> uuid.UUID:
        if isinstance(org_id, uuid.UUID):
            return org_id
        try:
            return uuid.UUID(str(org_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"Invalid organization id: {org_id!r}") from exc

    @staticmethod
    def _money(amount: float | Decimal | str | int) -> Decimal:
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
        if value <= 0:
            raise ValueError("amount_kzt must be positive")
        return value

    def is_low_balance(self, balance_kzt: float | Decimal | None) -> bool:
        if balance_kzt is None:
            return True
        return Decimal(str(balance_kzt)) < self.low_balance_threshold

    async def resolve_wallet_owner(
        self,
        db: AsyncSession,
        org_id: uuid.UUID | str | int,
    ) -> tuple[uuid.UUID, Organization]:
        org_uuid = self._as_uuid(org_id)
        org = await db.get(Organization, org_uuid)
        if org is None:
            raise ValueError(f"Organization '{org_uuid}' was not found.")
        if org.owner_user_id is None:
            raise ValueError(f"Organization '{org_uuid}' has no owner user.")
        return org.owner_user_id, org

    async def get_locked_subscription(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Subscription:
        """Lock the active subscription row for the duration of the transaction."""
        await pg_advisory_xact_lock_uuid(db, LOCK_NS_WALLET, user_id)

        result = await db.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        subscription = result.scalar_one_or_none()
        if subscription is not None:
            return subscription

        # Create then re-lock so concurrent creators still serialize.
        from app.services.billing_service import billing_service

        subscription = await billing_service._get_or_create_active_subscription(db, user_id)
        await db.flush()
        result = await db.execute(
            select(Subscription)
            .where(Subscription.id == subscription.id)
            .with_for_update()
        )
        locked = result.scalar_one()
        return locked

    async def deduct_wallet_balance(
        self,
        db: AsyncSession,
        org_id: uuid.UUID | str | int,
        amount_kzt: float | Decimal | str,
        *,
        description: str = "LLM usage debit",
        reference_id: str | None = None,
        bot_id: uuid.UUID | None = None,
        transaction_type: BillingTransactionType = BillingTransactionType.LLM_DEDUCTION,
        raise_on_insufficient: bool = True,
    ) -> WalletDeductionResult:
        """
        Atomically debit ``amount_kzt`` from the org owner's wallet.

        Uses ``SELECT FOR UPDATE`` on ``subscriptions`` so concurrent Celery
        workers cannot overdraw the same balance.
        """
        amount = self._money(amount_kzt)
        org_uuid = self._as_uuid(org_id)
        owner_id, _org = await self.resolve_wallet_owner(db, org_uuid)

        ref = (reference_id or "").strip() or None
        if ref is not None:
            existing_id = await db.scalar(
                select(BillingTransaction.id)
                .where(BillingTransaction.reference_id == ref)
                .limit(1)
            )
            if existing_id is not None:
                subscription = await self.get_locked_subscription(db, owner_id)
                bal = Decimal(subscription.balance).quantize(Decimal("0.01"))
                logger.info(
                    "Wallet.debit_skipped_duplicate | reference={ref}",
                    ref=ref,
                )
                return WalletDeductionResult(
                    org_id=org_uuid,
                    user_id=owner_id,
                    subscription_id=subscription.id,
                    amount_kzt=amount,
                    balance_before=bal,
                    balance_after=bal,
                    transaction_id=existing_id,
                )

        subscription = await self.get_locked_subscription(db, owner_id)

        before = Decimal(subscription.balance).quantize(Decimal("0.01"))
        if before < amount:
            message = (
                f"Insufficient funds: balance={before} KZT, required={amount} KZT "
                f"(org={org_uuid})."
            )
            logger.warning(
                "Wallet.insufficient_funds | org={org} balance={bal} required={req}",
                org=org_uuid,
                bal=str(before),
                req=str(amount),
            )
            if bot_id is not None:
                diagnostic_log_service.schedule_log(
                    bot_id=bot_id,
                    error_type=DiagnosticErrorType.INSUFFICIENT_FUNDS,
                    error_message=message,
                )
            if raise_on_insufficient:
                raise InsufficientFundsException(
                    message,
                    org_id=org_uuid,
                    balance=before,
                    required=amount,
                )
            # Soft clamp — should only be used by legacy paths.
            amount = before

        after = (before - amount).quantize(Decimal("0.01"))
        subscription.balance = after

        txn = BillingTransaction(
            user_id=owner_id,
            subscription_id=subscription.id,
            organization_id=org_uuid,
            transaction_type=transaction_type,
            status=BillingTransactionStatus.SUCCESS,
            amount=amount,
            currency="KZT",
            description=description[:512],
            reference_id=ref,
        )
        try:
            db.add(txn)
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            if ref is not None and is_unique_violation(exc):
                existing_id = await db.scalar(
                    select(BillingTransaction.id)
                    .where(BillingTransaction.reference_id == ref)
                    .limit(1)
                )
                if existing_id is not None:
                    subscription = await self.get_locked_subscription(db, owner_id)
                    bal = Decimal(subscription.balance).quantize(Decimal("0.01"))
                    logger.info(
                        "Wallet.debit_skipped_duplicate_db | reference={ref}",
                        ref=ref,
                    )
                    return WalletDeductionResult(
                        org_id=org_uuid,
                        user_id=owner_id,
                        subscription_id=subscription.id,
                        amount_kzt=amount,
                        balance_before=bal,
                        balance_after=bal,
                        transaction_id=existing_id,
                    )
            raise DuplicateTransactionError(
                f"Duplicate billing transaction reference '{ref}'.",
                reference_id=ref,
            ) from exc

        logger.info(
            "Wallet.deducted | org={org} amount={amount} before={before} after={after} txn={txn}",
            org=org_uuid,
            amount=str(amount),
            before=str(before),
            after=str(after),
            txn=txn.id,
        )
        return WalletDeductionResult(
            org_id=org_uuid,
            user_id=owner_id,
            subscription_id=subscription.id,
            amount_kzt=amount,
            balance_before=before,
            balance_after=after,
            transaction_id=txn.id,
        )

    async def credit_wallet_balance(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        amount_kzt: float | Decimal | str,
        organization_id: uuid.UUID | None = None,
        description: str = "Wallet top-up",
        reference_id: str | None = None,
        transaction_type: BillingTransactionType = BillingTransactionType.TOP_UP,
    ) -> WalletDeductionResult:
        """Credit wallet under row lock (Stripe / manual top-ups)."""
        amount = self._money(amount_kzt)

        # Idempotency FIRST — never mutate balance for a duplicate reference_id.
        if reference_id:
            existing = await db.scalar(
                select(BillingTransaction.id)
                .where(BillingTransaction.reference_id == reference_id)
                .limit(1)
            )
            if existing is not None:
                subscription = await self.get_locked_subscription(db, user_id)
                bal = Decimal(subscription.balance).quantize(Decimal("0.01"))
                logger.info(
                    "Wallet.credit_skipped_duplicate | reference={ref}",
                    ref=reference_id,
                )
                return WalletDeductionResult(
                    org_id=organization_id or user_id,
                    user_id=user_id,
                    subscription_id=subscription.id,
                    amount_kzt=amount,
                    balance_before=bal,
                    balance_after=bal,
                    transaction_id=existing if isinstance(existing, uuid.UUID) else None,
                )

        subscription = await self.get_locked_subscription(db, user_id)
        before = Decimal(subscription.balance).quantize(Decimal("0.01"))

        # Re-check under row lock to close concurrent duplicate races.
        if reference_id:
            existing = await db.scalar(
                select(BillingTransaction.id)
                .where(BillingTransaction.reference_id == reference_id)
                .limit(1)
            )
            if existing is not None:
                logger.info(
                    "Wallet.credit_skipped_duplicate_locked | reference={ref}",
                    ref=reference_id,
                )
                return WalletDeductionResult(
                    org_id=organization_id or user_id,
                    user_id=user_id,
                    subscription_id=subscription.id,
                    amount_kzt=amount,
                    balance_before=before,
                    balance_after=before,
                    transaction_id=existing if isinstance(existing, uuid.UUID) else None,
                )

        after = (before + amount).quantize(Decimal("0.01"))
        subscription.balance = after

        txn = BillingTransaction(
            user_id=user_id,
            subscription_id=subscription.id,
            organization_id=organization_id,
            transaction_type=transaction_type,
            status=BillingTransactionStatus.SUCCESS,
            amount=amount,
            currency="KZT",
            description=description[:512],
            reference_id=reference_id,
        )
        try:
            db.add(txn)
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            if reference_id and is_unique_violation(exc):
                existing = await db.scalar(
                    select(BillingTransaction.id)
                    .where(BillingTransaction.reference_id == reference_id)
                    .limit(1)
                )
                if existing is not None:
                    subscription = await self.get_locked_subscription(db, user_id)
                    bal = Decimal(subscription.balance).quantize(Decimal("0.01"))
                    logger.info(
                        "Wallet.credit_skipped_duplicate_db | reference={ref}",
                        ref=reference_id,
                    )
                    return WalletDeductionResult(
                        org_id=organization_id or user_id,
                        user_id=user_id,
                        subscription_id=subscription.id,
                        amount_kzt=amount,
                        balance_before=bal,
                        balance_after=bal,
                        transaction_id=existing if isinstance(existing, uuid.UUID) else None,
                    )
            raise DuplicateTransactionError(
                f"Duplicate billing transaction reference '{reference_id}'.",
                reference_id=reference_id,
            ) from exc
        logger.info(
            "Wallet.credited | user={user} amount={amount} after={after} ref={ref}",
            user=user_id,
            amount=str(amount),
            after=str(after),
            ref=reference_id,
        )
        return WalletDeductionResult(
            org_id=organization_id or user_id,
            user_id=user_id,
            subscription_id=subscription.id,
            amount_kzt=amount,
            balance_before=before,
            balance_after=after,
            transaction_id=txn.id,
        )

    async def get_org_balance_kzt(
        self,
        db: AsyncSession,
        org_id: uuid.UUID | str | int,
    ) -> Decimal:
        owner_id, _ = await self.resolve_wallet_owner(db, org_id)
        from app.services.billing_service import billing_service

        sub = await billing_service._get_or_create_active_subscription(db, owner_id)
        return Decimal(sub.balance).quantize(Decimal("0.01"))


wallet_service = WalletService()


async def check_wallet_before_generation(org_id, db=None):
    """Spec §1.4 facade — token wallet, non-locking."""
    from app.services.token_wallet_service import token_wallet_service

    if db is None:
        raise TypeError("check_wallet_before_generation requires an AsyncSession")
    return await token_wallet_service.check_wallet_before_generation(db, org_id)
