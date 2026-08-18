"""
Financial billing edge cases — webhook idempotency, ledger integrity,
soft credit limits, subscription expiration.

Steps:
  A) 10 parallel identical payment webhooks → +balance once, 1 CreditTransaction
  B) 30 parallel deducts + 10 parallel credits → balance == SUM(ledger)
  C) Balance=2, LLM needs 10 → soft 402 / insufficient, balance never negative
  D) ACTIVE subscription with current_period_end in the past → Free limits

Usage:
  pytest backend/tests/e2e/test_financial_billing_edge_cases.py -v -s
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.billing import (
    OrganizationSubscription,
    OrganizationSubscriptionStatus,
    PaymentInvoice,
    PaymentInvoiceStatus,
    PaymentProvider,
)
from app.models.billing.credit_transaction import CreditTransaction
from app.models.billing.organization_wallet import OrganizationWallet
from app.models.core_models import Company, UserCompanyWorkspace, UserRole
from app.models.users import User
from app.services.billing.wallet_service import InsufficientFundsError, wallet_service
from app.services.billing_service import PLAN_AGENT_LIMITS
from app.services.llm.base import InsufficientCreditsForLLMError, LLMResponse
from app.services.llm.gateway import ResilientLLMGateway
from app.models.core_models import SubscriptionPlanName
from main import app
from tests.llm.test_llm_billing import FakeProvider

# Free-tier token cap mirrored from quota_service (avoid circular import at collect time).
FREE_TOKEN_MONTH_LIMIT = 100_000
FREE_BOT_LIMIT = PLAN_AGENT_LIMITS[SubscriptionPlanName.FREE]

FIXED_BUGS: list[str] = [
    "wallet_service credit/deduct IntegrityError path: SAVEPOINT (begin_nested) so "
    "unique-ref races do not abort an outer payment settlement transaction.",
    "process_successful_payment: replaced brittle async with db.begin() with "
    "explicit begin/commit that cooperates with request-scoped sessions.",
    "OrganizationSubscription expiration was never enforced — expired ACTIVE rows "
    "kept Pro/Enterprise quotas; expire_organization_subscription_if_needed + "
    "quota_service._plan now roll back to Free limits.",
    "POST /webhooks/payments/{provider} was shadowed by /webhooks/{channel}/{bot_id} "
    "(payments/manual parsed as channel+UUID) → HTTP 422; payment route registered first.",
]


@dataclass
class FinancialReport:
    webhook_idempotent: bool = False
    webhook_single_credit_tx: bool = False
    ledger_reconciled: bool = False
    soft_limit_402: bool = False
    balance_never_negative: bool = False
    subscription_expired_to_free: bool = False
    notes: list[str] = field(default_factory=list)

    def print_summary(self) -> None:
        yes = lambda v: "PASS" if v else "FAIL"
        print("\n" + "=" * 64)
        print("  QA REPORT — Financial billing integrity")
        print("=" * 64)
        print(f"  Webhook idempotency (10x)     : {yes(self.webhook_idempotent)}")
        print(f"  Single CreditTransaction      : {yes(self.webhook_single_credit_tx)}")
        print(f"  Ledger == wallet balance      : {yes(self.ledger_reconciled)}")
        print(f"  Soft limit / insufficient LLM : {yes(self.soft_limit_402)}")
        print(f"  Balance never negative        : {yes(self.balance_never_negative)}")
        print(f"  Expired sub -> Free limits    : {yes(self.subscription_expired_to_free)}")
        if FIXED_BUGS:
            print("\n  Fixed bugs during run:")
            for bug in FIXED_BUGS:
                print(f"    - {bug}")
        if self.notes:
            print("\n  Notes:")
            for note in self.notes:
                print(f"    * {note}")
        print("=" * 64 + "\n")


REPORT = FinancialReport()


@pytest.fixture(scope="session")
def fin_database_url():
    """Ephemeral Postgres via testcontainers, else DATABASE_URL fallback."""
    from tests.conftest import _run_alembic_upgrade, _to_asyncpg_url

    container = None
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine")
        container.start()
        url = _to_asyncpg_url(container.get_connection_url())
        _run_alembic_upgrade(url)
        yield url
        return
    except Exception as docker_exc:  # noqa: BLE001
        print(f"[fin-e2e] testcontainers unavailable: {docker_exc} — trying DATABASE_URL")
        if container is not None:
            with suppress(Exception):
                container.stop()
            container = None

    raw = (settings.DATABASE_URL or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        pytest.skip("No Docker and no DATABASE_URL for financial e2e test.")

    url = _to_asyncpg_url(raw)
    try:
        _run_alembic_upgrade(url)
    except Exception as mig_exc:  # noqa: BLE001
        print(f"[fin-e2e] alembic upgrade warning (continuing): {mig_exc}")
    yield url
    if container is not None:
        with suppress(Exception):
            container.stop()


@pytest.fixture
async def fin_session_factory(
    fin_database_url: str,
) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        fin_database_url,
        pool_size=25,
        max_overflow=40,
        pool_pre_ping=True,
        pool_timeout=20,
    )
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_org(
    factory: async_sessionmaker[AsyncSession],
    *,
    balance: int = 0,
    email_prefix: str = "fin",
) -> tuple[uuid.UUID, uuid.UUID]:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with factory() as db:
        db.add(
            User(
                id=user_id,
                email=f"{email_prefix}-{org_id.hex[:10]}@mp.ai.test",
                hashed_password=hash_password("Fin-Test-Pass-9!"),
                full_name="Finance QA Owner",
                company_name="Finance QA Org",
                company_id=org_id,
                role=UserRole.OWNER,
                is_active=True,
                is_verified=True,
                timezone="Asia/Almaty",
            )
        )
        await db.flush()
        db.add(
            Company(
                id=org_id,
                name=f"Finance QA {org_id.hex[:8]}",
                owner_user_id=user_id,
                timezone="Asia/Almaty",
                stripe_plan="PRO",
            )
        )
        db.add(
            UserCompanyWorkspace(
                user_id=user_id,
                company_id=org_id,
                role=UserRole.OWNER,
            )
        )
        await db.flush()
        await wallet_service.get_or_create_wallet(db, org_id, initial_balance=balance)
        await db.commit()
    return org_id, user_id


def _sign_manual(body: bytes) -> str:
    secret = (settings.PAYMENT_WEBHOOK_DEV_SECRET or "dev-payment-secret").encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Step A — Webhook idempotency under concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_a_parallel_webhooks_credit_once(
    fin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id, _ = await _seed_org(fin_session_factory, balance=0, email_prefix="wh")
    tokens = 50_000
    external_id = f"manual:{uuid.uuid4()}"

    async with fin_session_factory() as db:
        db.add(
            PaymentInvoice(
                organization_id=org_id,
                provider=PaymentProvider.MANUAL.value,
                external_id=external_id,
                amount=Decimal("10.00"),
                currency="USD",
                tokens_allocated=tokens,
                status=PaymentInvoiceStatus.PENDING,
                item_type="topup",
                package_id="topup_50k",
                idempotency_key=f"fin-wh-{uuid.uuid4()}",
            )
        )
        await db.commit()

    body = json.dumps({"external_payment_id": external_id}).encode()
    sig = _sign_manual(body)

    async def _override_get_db():
        async with fin_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                with suppress(Exception):
                    await session.rollback()
                raise
            finally:
                with suppress(Exception):
                    await session.close()

    from app.core.database import get_db as core_get_db
    from app.db.session import get_db as session_get_db

    app.dependency_overrides[core_get_db] = _override_get_db
    app.dependency_overrides[session_get_db] = _override_get_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:

            async def fire() -> int:
                resp = await client.post(
                    "/api/v1/webhooks/payments/manual",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-payment-signature": sig,
                    },
                )
                return resp.status_code

            statuses = await asyncio.gather(*[fire() for _ in range(10)])
    finally:
        app.dependency_overrides.pop(core_get_db, None)
        app.dependency_overrides.pop(session_get_db, None)

    assert all(s == 200 for s in statuses), statuses

    async with fin_session_factory() as db:
        balance = await wallet_service.get_balance(db, org_id)
        deposit_rows = (
            await db.scalars(
                select(CreditTransaction).where(
                    CreditTransaction.wallet_id == org_id,
                    CreditTransaction.transaction_type == "DEPOSIT",
                )
            )
        ).all()
        invoice = await db.scalar(
            select(PaymentInvoice).where(PaymentInvoice.external_id == external_id)
        )

    assert balance == tokens, f"balance={balance}, expected single credit of {tokens}"
    assert len(deposit_rows) == 1, f"expected 1 DEPOSIT row, got {len(deposit_rows)}"
    assert int(deposit_rows[0].amount) == tokens
    assert invoice is not None and invoice.status == PaymentInvoiceStatus.SUCCEEDED

    REPORT.webhook_idempotent = True
    REPORT.webhook_single_credit_tx = True
    REPORT.notes.append(
        f"webhook: 10 parallel POSTs -> balance={balance}, DEPOSIT rows={len(deposit_rows)}"
    )


# ---------------------------------------------------------------------------
# Step B — Parallel deducts + credits, ledger reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_b_parallel_mutations_ledger_reconciles(
    fin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    initial = 1_000
    org_id, _ = await _seed_org(fin_session_factory, balance=initial, email_prefix="race")

    # Distinct deduct amounts that fit under 1000 with some InsufficientFunds.
    deduct_amounts = [10 + (i % 17) for i in range(30)]  # 10..26 repeating
    credit_amounts = [5 + i for i in range(10)]  # 5..14

    async def do_deduct(i: int, amount: int) -> str:
        async with fin_session_factory() as session:
            try:
                await wallet_service.deduct_credits(
                    session,
                    org_id,
                    amount,
                    "llm_tokens",
                    reference_id=f"race-deduct-{org_id.hex[:8]}-{i}",
                )
                return "ok"
            except InsufficientFundsError:
                await session.rollback()
                return "insufficient"
            except Exception:
                await session.rollback()
                raise

    async def do_credit(i: int, amount: int) -> str:
        async with fin_session_factory() as session:
            try:
                await wallet_service.credit_credits(
                    session,
                    org_id,
                    amount,
                    "DEPOSIT",
                    reference_id=f"race-credit-{org_id.hex[:8]}-{i}",
                    description="parallel topup",
                )
                return "ok"
            except Exception:
                await session.rollback()
                raise

    deduct_tasks = [do_deduct(i, a) for i, a in enumerate(deduct_amounts)]
    credit_tasks = [do_credit(i, a) for i, a in enumerate(credit_amounts)]
    results = await asyncio.gather(*(deduct_tasks + credit_tasks))

    async with fin_session_factory() as db:
        balance = await wallet_service.get_balance(db, org_id)
        ledger_sum = await db.scalar(
            select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                CreditTransaction.wallet_id == org_id
            )
        )
        wallet = await db.get(OrganizationWallet, org_id)

    # initial wallet row had no seed ledger — reconcile as:
    # balance == initial + SUM(transactions)  when seed had no txn,
    # OR balance == SUM(all txns) if we also wrote an opening balance txn.
    # Our seed uses get_or_create_wallet(initial_balance) without ledger row,
    # so expected: balance == initial + ledger_sum.
    expected = initial + int(ledger_sum or 0)
    assert int(wallet.balance) == balance
    assert balance == expected, (
        f"ledger drift: balance={balance} initial={initial} "
        f"ledger_sum={ledger_sum} expected={expected}"
    )
    assert balance >= 0

    ok_deducts = results[:30].count("ok")
    REPORT.ledger_reconciled = True
    REPORT.balance_never_negative = balance >= 0
    REPORT.notes.append(
        f"race: balance={balance} == {initial}+{int(ledger_sum or 0)}; "
        f"deducts ok={ok_deducts}/30 credits=10/10"
    )


# ---------------------------------------------------------------------------
# Step C — Soft / hard credit limit during LLM call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_c_insufficient_credits_soft_fail(
    fin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id, _ = await _seed_org(fin_session_factory, balance=2, email_prefix="soft")

    provider = FakeProvider(
        LLMResponse(
            content="should-not-run",
            tool_calls=None,
            prompt_tokens=5000,
            completion_tokens=5000,
            model_name="gpt-4o",
        )
    )
    gateway = ResilientLLMGateway([provider], wallet_service=wallet_service)

    async with fin_session_factory() as db:
        with pytest.raises(InsufficientCreditsForLLMError) as exc_info:
            await gateway.complete_for_organization(
                db,
                org_id,
                [{"role": "user", "content": "expensive prompt that needs credits"}],
                max_tokens=2000,
                model="gpt-4o",
                reference_id=f"soft-limit-{uuid.uuid4()}",
                use_org_providers=False,
            )
        await db.rollback()

    assert exc_info.value.status_code == 402
    assert provider.complete_calls == 0

    async with fin_session_factory() as db:
        balance = await wallet_service.get_balance(db, org_id)
        tx_count = await db.scalar(
            select(func.count()).select_from(CreditTransaction).where(
                CreditTransaction.wallet_id == org_id
            )
        )

    assert balance == 2
    assert int(tx_count or 0) == 0
    REPORT.soft_limit_402 = True
    REPORT.balance_never_negative = True
    REPORT.notes.append(
        f"soft-limit: balance stayed at {balance}; LLM blocked with 402; "
        f"provider_calls={provider.complete_calls}"
    )


# ---------------------------------------------------------------------------
# Step D — Subscription expiration → Free plan limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_d_expired_subscription_falls_back_to_free(
    fin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.services.quota_service import quota_service

    org_id, _ = await _seed_org(fin_session_factory, balance=100, email_prefix="sub")

    async with fin_session_factory() as db:
        db.add(
            OrganizationSubscription(
                organization_id=org_id,
                plan_id="pro",
                status=OrganizationSubscriptionStatus.ACTIVE,
                current_period_end=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await db.commit()

    async with fin_session_factory() as db:
        limits = await quota_service.get_organization_limits(db, org_id)
        await db.commit()

        sub = await db.scalar(
            select(OrganizationSubscription).where(
                OrganizationSubscription.organization_id == org_id
            )
        )
        company = await db.get(Company, org_id)

    assert limits["plan"] == SubscriptionPlanName.FREE.value
    assert int(limits["bots_max"]) == FREE_BOT_LIMIT
    assert int(limits["tokens_month_max"]) == FREE_TOKEN_MONTH_LIMIT
    assert sub is not None
    assert sub.status == OrganizationSubscriptionStatus.CANCELED
    assert sub.plan_id == "free"
    assert company is not None
    assert str(getattr(company, "stripe_plan", "")).upper() == "FREE"

    REPORT.subscription_expired_to_free = True
    REPORT.notes.append(
        f"subscription: expired ACTIVE pro -> plan={limits['plan']} "
        f"bots_max={limits['bots_max']} tokens_month={limits['tokens_month_max']}"
    )


@pytest.fixture(scope="module", autouse=True)
def _print_financial_report():
    yield
    REPORT.print_summary()
