"""WalletService credit idempotency — duplicate reference_id must not mutate balance."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.core_models import (
    BillingTransaction,
    BillingTransactionStatus,
    BillingTransactionType,
    SubscriptionStatus,
)
from app.services.wallet_service import WalletService


class _ExecuteResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value


class WalletFakeSession:
    """Async session stub that tracks ORM mutations and BillingTransaction lookups."""

    def __init__(self, subscription: Any, *, existing_reference: str | None = None) -> None:
        self.subscription = subscription
        self.existing_reference = existing_reference
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, stmt: Any) -> _ExecuteResult:
        # FOR UPDATE lock path returns the subscription.
        return _ExecuteResult(self.subscription)

    async def scalar(self, stmt: Any) -> Any:
        # Idempotency lookup on BillingTransaction.reference_id
        if self.existing_reference is None:
            return None
        # Any reference query with a matching stored id returns a UUID.
        return uuid.uuid4()

    async def flush(self) -> None:
        self.flushed += 1

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def begin_nested(self) -> "_NestedSavepoint":
        return _NestedSavepoint()


class _NestedSavepoint:
    async def __aenter__(self) -> "_NestedSavepoint":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


@pytest.mark.asyncio
async def test_credit_wallet_skips_duplicate_reference_without_mutating_balance() -> None:
    user_id = uuid.uuid4()
    subscription = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        balance=Decimal("1000.00"),
        status=SubscriptionStatus.ACTIVE,
    )
    session = WalletFakeSession(subscription, existing_reference="stripe_evt_dup_1")
    service = WalletService()

    # First-call simulation: reference already exists from a prior committed credit.
    result = await service.credit_wallet_balance(
        session,
        user_id=user_id,
        amount_kzt=500,
        organization_id=user_id,
        description="Stripe top-up",
        reference_id="stripe_evt_dup_1",
        transaction_type=BillingTransactionType.TOP_UP,
    )

    assert subscription.balance == Decimal("1000.00")
    assert result.balance_before == Decimal("1000.00")
    assert result.balance_after == Decimal("1000.00")
    assert session.added == []
    assert session.flushed == 0


@pytest.mark.asyncio
async def test_credit_wallet_applies_balance_when_reference_is_new() -> None:
    user_id = uuid.uuid4()
    subscription = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        balance=Decimal("1000.00"),
        status=SubscriptionStatus.ACTIVE,
    )
    session = WalletFakeSession(subscription, existing_reference=None)
    service = WalletService()

    result = await service.credit_wallet_balance(
        session,
        user_id=user_id,
        amount_kzt="250.50",
        organization_id=user_id,
        description="Stripe top-up",
        reference_id="stripe_evt_new_1",
        transaction_type=BillingTransactionType.TOP_UP,
    )

    assert subscription.balance == Decimal("1250.50")
    assert result.balance_before == Decimal("1000.00")
    assert result.balance_after == Decimal("1250.50")
    assert len(session.added) == 1
    txn = session.added[0]
    assert isinstance(txn, BillingTransaction)
    assert txn.reference_id == "stripe_evt_new_1"
    assert txn.amount == Decimal("250.50")
    assert txn.status == BillingTransactionStatus.SUCCESS
    assert session.flushed == 1


@pytest.mark.asyncio
async def test_credit_wallet_duplicate_after_successful_credit_is_noop() -> None:
    """Simulate two sequential credits with the same reference_id in one session."""
    user_id = uuid.uuid4()
    subscription = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        balance=Decimal("100.00"),
        status=SubscriptionStatus.ACTIVE,
    )
    service = WalletService()
    seen_refs: set[str] = set()

    class SequentialSession(WalletFakeSession):
        async def scalar(self, stmt: Any) -> Any:
            # After first flush we "persist" the reference.
            if "stripe_same" in seen_refs:
                return uuid.uuid4()
            return None

        def add(self, obj: Any) -> None:
            super().add(obj)
            if getattr(obj, "reference_id", None):
                seen_refs.add(str(obj.reference_id))

    session = SequentialSession(subscription)

    first = await service.credit_wallet_balance(
        session,
        user_id=user_id,
        amount_kzt=50,
        reference_id="stripe_same",
    )
    second = await service.credit_wallet_balance(
        session,
        user_id=user_id,
        amount_kzt=50,
        reference_id="stripe_same",
    )

    assert first.balance_after == Decimal("150.00")
    assert second.balance_after == Decimal("150.00")
    assert subscription.balance == Decimal("150.00")
    assert len(session.added) == 1
