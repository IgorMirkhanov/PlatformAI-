"""Payment webhook idempotency and wallet credit tests (requires Docker Postgres)."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import get_db
from app.models.billing import PaymentInvoice, PaymentInvoiceStatus, PaymentProvider
from app.models.core_models import Company
from app.services.billing.payment_billing_service import payment_billing_service
from app.services.billing.wallet_service import wallet_service
from main import app

pytestmark = pytest.mark.usefixtures("real_database_url")


async def _seed_org(db: AsyncSession) -> uuid.UUID:
    from app.models.core_models import UserRole
    from app.models.users import User

    owner_id = uuid.uuid4()
    org_id = uuid.uuid4()
    db.add(
        User(
            id=owner_id,
            email=f"pay-{owner_id.hex[:8]}@test.local",
            hashed_password="!",
            company_name="PayTest Org",
            company_id=org_id,
            role=UserRole.OWNER,
        )
    )
    # Explicit flush before adding Company: SQLAlchemy's automatic cross-table
    # insert ordering doesn't reliably put users before companies in this schema
    # (reproduced standalone — companies_owner_user_id_fkey fires because the
    # User insert never happens first without this), so don't rely on it.
    await db.flush()
    db.add(
        Company(
            id=org_id,
            name=f"PayTest {org_id.hex[:8]}",
            owner_user_id=owner_id,
        )
    )
    await db.flush()
    await wallet_service.get_or_create_wallet(db, org_id)
    await db.commit()
    return org_id


@pytest.mark.asyncio
async def test_process_successful_payment_idempotent(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_session_factory() as db:
        org_id = await _seed_org(db)

        invoice = PaymentInvoice(
            organization_id=org_id,
            provider=PaymentProvider.MANUAL.value,
            external_id=f"manual:{uuid.uuid4()}",
            amount=10,
            currency="USD",
            tokens_allocated=100_000,
            status=PaymentInvoiceStatus.PENDING,
            item_type="topup",
            package_id="topup_100k",
            idempotency_key=f"test-{uuid.uuid4()}",
        )
        db.add(invoice)
        await db.commit()
        await db.refresh(invoice)

        external = invoice.external_id
        assert external is not None

        assert await payment_billing_service.process_successful_payment(
            db,
            external_payment_id=external,
            provider=PaymentProvider.MANUAL.value,
        )
        balance_after_first = await wallet_service.get_balance(db, org_id)

        assert await payment_billing_service.process_successful_payment(
            db,
            external_payment_id=external,
            provider=PaymentProvider.MANUAL.value,
        )
        balance_after_second = await wallet_service.get_balance(db, org_id)

        assert balance_after_first == 100_000
        assert balance_after_second == balance_after_first


@pytest.mark.asyncio
async def test_manual_payment_webhook_endpoint(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # The webhook goes through the real ASGI app (its own `Depends(get_db)`), not the
    # `db` session this test holds directly — override the app's DB dependency so the
    # endpoint's session is the same testcontainers Postgres `_seed_org` wrote to,
    # same pattern as tests/crm/test_e2e_business_flow_real_db.py.
    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with real_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_db
    try:
        async with real_session_factory() as db:
            org_id = await _seed_org(db)
            invoice = PaymentInvoice(
                organization_id=org_id,
                provider=PaymentProvider.MANUAL.value,
                external_id=f"manual:{uuid.uuid4()}",
                amount=80,
                currency="USD",
                tokens_allocated=1_000_000,
                status=PaymentInvoiceStatus.PENDING,
                item_type="topup",
                package_id="topup_1m",
                idempotency_key=f"wh-{uuid.uuid4()}",
            )
            db.add(invoice)
            await db.commit()

            body = json.dumps({"external_payment_id": invoice.external_id}).encode()
            secret = (settings.PAYMENT_WEBHOOK_DEV_SECRET or "dev-payment-secret").encode()
            sig = hmac.new(secret, body, hashlib.sha256).hexdigest()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                for _ in range(2):
                    response = await client.post(
                        "/api/v1/webhooks/payments/manual",
                        content=body,
                        headers={
                            "content-type": "application/json",
                            "x-payment-signature": sig,
                        },
                    )
                    assert response.status_code == 200

            balance = await wallet_service.get_balance(db, org_id)
            assert balance == 1_000_000
    finally:
        app.dependency_overrides.clear()
