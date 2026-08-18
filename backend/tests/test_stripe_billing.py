"""Tests — Stripe billing service (organization-scoped, mocked Stripe SDK)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.core_models import SubscriptionPlanName
from app.services.stripe_billing_service import StripeBillingService, StripeNotConfigured


class _FakeDb:
    def __init__(self, link: Any = None):
        self.link = link
        self.added: list[Any] = []

    async def scalar(self, _stmt):
        return self.link

    async def get(self, _model, _pk):
        return SimpleNamespace(
            id=_pk,
            owner_user_id=uuid.uuid4(),
            stripe_customer_id=None,
            stripe_subscription_id=None,
            stripe_status=None,
            stripe_plan=None,
        )

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_get_or_create_customer_existing(monkeypatch):
    svc = StripeBillingService()
    org_id = uuid.uuid4()
    existing = SimpleNamespace(
        organization_id=org_id,
        stripe_customer_id="cus_existing",
        billing_email=None,
    )
    db = _FakeDb(link=existing)
    cid = await svc.get_or_create_customer(
        db,  # type: ignore[arg-type]
        organization_id=org_id,
        email="billing@org.test",
    )
    assert cid == "cus_existing"
    assert existing.billing_email == "billing@org.test"


@pytest.mark.asyncio
async def test_get_or_create_customer_creates(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(svc, "enabled", lambda: True)
    org_id = uuid.uuid4()
    db = _FakeDb(link=None)

    class _Stripe:
        class Customer:
            @staticmethod
            def create(**kwargs):
                return {"id": "cus_new"}

        api_key = None

    monkeypatch.setattr(svc, "_stripe", lambda: _Stripe)
    cid = await svc.get_or_create_customer(
        db,  # type: ignore[arg-type]
        organization_id=org_id,
        email="a@b.c",
        user_id=uuid.uuid4(),
    )
    assert cid == "cus_new"
    assert len(db.added) >= 1


@pytest.mark.asyncio
async def test_org_billing_snapshot():
    svc = StripeBillingService()
    org_id = uuid.uuid4()
    customer = SimpleNamespace(
        status="active",
        plan_name="PRO",
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1",
    )
    org = SimpleNamespace(
        stripe_status="active",
        stripe_plan="PRO",
        stripe_subscription_id="sub_1",
    )

    class _Db:
        async def scalar(self, _stmt):
            return customer

        async def get(self, _model, _pk):
            return org

    snap = await svc.get_org_billing_snapshot(_Db(), organization_id=org_id)  # type: ignore[arg-type]
    assert snap["has_customer"] is True
    assert snap["plan"] == "PRO"
    assert snap["stripe_status"] == "active"


@pytest.mark.asyncio
async def test_checkout_with_explicit_price_id(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(svc, "enabled", lambda: True)

    async def fake_customer(*_a, **_k):
        return "cus_123"

    class _Stripe:
        class checkout:
            class Session:
                @staticmethod
                def create(**kwargs):
                    assert kwargs["line_items"][0]["price"] == "price_custom"
                    return {"id": "cs_x", "url": "https://checkout.stripe.test/x"}

        api_key = None

    monkeypatch.setattr(svc, "get_or_create_customer", fake_customer)
    monkeypatch.setattr(svc, "_stripe", lambda: _Stripe)
    result = await svc.create_checkout_session(
        _FakeDb(),  # type: ignore[arg-type]
        organization_id=uuid.uuid4(),
        email="a@b.c",
        price_id="price_custom",
        success_url="https://app/ok",
        cancel_url="https://app/cancel",
    )
    assert result["url"]



@pytest.mark.asyncio
async def test_checkout_creates_session(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(svc, "enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.stripe_billing_service.settings.STRIPE_PRICE_PRO",
        "price_pro_test",
        raising=False,
    )

    async def fake_customer(*_a, **_k):
        return "cus_123"

    class _Stripe:
        class checkout:
            class Session:
                @staticmethod
                def create(**kwargs):
                    assert "organization_id" in kwargs["metadata"]
                    return {"id": "cs_test", "url": "https://checkout.stripe.test/cs"}

        api_key = None

    monkeypatch.setattr(svc, "get_or_create_customer", fake_customer)
    monkeypatch.setattr(svc, "_stripe", lambda: _Stripe)
    org_id = uuid.uuid4()

    result = await svc.create_checkout_session(
        _FakeDb(),  # type: ignore[arg-type]
        organization_id=org_id,
        email="a@b.c",
        plan=SubscriptionPlanName.PRO,
        success_url="https://app/ok",
        cancel_url="https://app/cancel",
    )
    assert result["url"].startswith("https://checkout.stripe")
    assert result["organization_id"] == str(org_id)


@pytest.mark.asyncio
async def test_meter_noop_when_disabled(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(
        "app.services.stripe_billing_service.settings.STRIPE_METERING_ENABLED",
        False,
        raising=False,
    )
    out = await svc.report_meter_event(
        stripe_customer_id="cus_x",
        event_name="llm_tokens",
        quantity=10,
    )
    assert out is None


def test_not_configured():
    svc = StripeBillingService()
    if not svc.enabled():
        with pytest.raises(StripeNotConfigured):
            svc._stripe()


@pytest.mark.asyncio
async def test_portal_session(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(svc, "enabled", lambda: True)
    link = SimpleNamespace(
        organization_id=uuid.uuid4(),
        stripe_customer_id="cus_portal",
        stripe_subscription_id=None,
        plan_name="PRO",
        status="active",
    )
    db = _FakeDb(link=link)

    class _Stripe:
        class billing_portal:
            class Session:
                @staticmethod
                def create(**kwargs):
                    return {"url": "https://billing.stripe.test/session"}

        api_key = None

    monkeypatch.setattr(svc, "_stripe", lambda: _Stripe)

    result = await svc.create_portal_session(
        db,  # type: ignore[arg-type]
        organization_id=link.organization_id,
        return_url="https://app/billing",
    )
    assert result["url"].startswith("https://billing.stripe")


@pytest.mark.asyncio
async def test_webhook_idempotent(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(svc, "enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.stripe_billing_service.settings.STRIPE_WEBHOOK_SECRET",
        "whsec_test",
        raising=False,
    )

    existing = SimpleNamespace(event_id="evt_dup")
    db = _FakeDb(link=existing)

    class _Stripe:
        class Webhook:
            @staticmethod
            def construct_event(payload, signature, secret):
                return {
                    "id": "evt_dup",
                    "type": "checkout.session.completed",
                    "data": {"object": {}},
                }

        api_key = None

    monkeypatch.setattr(svc, "_stripe", lambda: _Stripe)

    out = await svc.handle_webhook(db, b"{}", "sig")  # type: ignore[arg-type]
    assert out["status"] == "duplicate"


@pytest.mark.asyncio
async def test_meter_event_when_enabled(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(svc, "enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.stripe_billing_service.settings.STRIPE_METERING_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.stripe_billing_service.settings.STRIPE_METER_EVENT_NAME",
        "llm_tokens",
        raising=False,
    )

    class _MeterEvent:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(identifier="me_1")

    class _Stripe:
        class billing:
            MeterEvent = _MeterEvent

        api_key = None

    monkeypatch.setattr(svc, "_stripe", lambda: _Stripe)
    out = await svc.report_meter_event(
        stripe_customer_id="cus_x",
        event_name="llm_tokens",
        quantity=5,
    )
    assert out is not None
    assert out["id"] == "me_1"


@pytest.mark.asyncio
async def test_webhook_checkout_applies_plan(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(svc, "enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.stripe_billing_service.settings.STRIPE_WEBHOOK_SECRET",
        "whsec_test",
        raising=False,
    )

    org_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    sub = SimpleNamespace(
        id=uuid.uuid4(),
        plan_name=SubscriptionPlanName.FREE,
        status=None,
        expires_at=None,
        balance=0,
    )
    customer = SimpleNamespace(
        organization_id=org_id,
        stripe_customer_id="cus_1",
        stripe_subscription_id=None,
        plan_name=None,
        status="none",
    )
    org = SimpleNamespace(
        id=org_id,
        owner_user_id=owner_id,
        stripe_customer_id=None,
        stripe_subscription_id=None,
        stripe_status=None,
        stripe_plan=None,
    )

    class _Db:
        def __init__(self):
            self.added = []
            self._n = 0

        async def scalar(self, _stmt):
            self._n += 1
            if self._n == 1:
                return None  # ProcessedStripeEvent
            return customer

        async def get(self, _model, pk):
            if pk == org_id:
                return org
            return None

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            return None

        async def commit(self):
            return None

    async def fake_sub(_db, uid):
        assert uid == owner_id
        return sub

    monkeypatch.setattr(
        "app.services.stripe_billing_service.billing_service._get_or_create_active_subscription",
        fake_sub,
    )

    class _Stripe:
        class Webhook:
            @staticmethod
            def construct_event(payload, signature, secret):
                return {
                    "id": "evt_new",
                    "type": "checkout.session.completed",
                    "data": {
                        "object": {
                            "metadata": {
                                "organization_id": str(org_id),
                                "plan": "PRO",
                            },
                            "customer": "cus_1",
                            "subscription": "sub_123",
                            "client_reference_id": str(org_id),
                        }
                    },
                }

        api_key = None

    monkeypatch.setattr(svc, "_stripe", lambda: _Stripe)
    out = await svc.handle_webhook(_Db(), b"{}", "sig")  # type: ignore[arg-type]
    assert out["status"] == "ok"
    assert sub.plan_name == SubscriptionPlanName.PRO
    assert customer.status == "active"
    assert org.stripe_status == "active"


@pytest.mark.asyncio
async def test_invoice_paid_extends_expiry(monkeypatch):
    svc = StripeBillingService()
    org_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    sub = SimpleNamespace(status=None, expires_at=None)
    link = SimpleNamespace(
        organization_id=org_id,
        user_id=owner_id,
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1",
        plan_name="PRO",
        status="active",
    )
    org = SimpleNamespace(
        owner_user_id=owner_id,
        stripe_customer_id=None,
        stripe_subscription_id=None,
        stripe_status=None,
        stripe_plan=None,
    )

    class _Db:
        async def scalar(self, _stmt):
            return link

        async def get(self, _model, _pk):
            return org

        async def flush(self):
            return None

    async def fake_sub(_db, uid):
        return sub

    monkeypatch.setattr(
        "app.services.stripe_billing_service.billing_service._get_or_create_active_subscription",
        fake_sub,
    )

    await svc._apply_invoice_paid(
        _Db(),  # type: ignore[arg-type]
        {
            "data": {
                "object": {
                    "customer": "cus_1",
                    "lines": {"data": [{"period": {"end": 1_900_000_000}}]},
                }
            }
        },
    )
    assert sub.expires_at is not None


@pytest.mark.asyncio
async def test_report_usage_for_org_noop_without_link(monkeypatch):
    svc = StripeBillingService()
    monkeypatch.setattr(
        "app.services.stripe_billing_service.settings.STRIPE_METERING_ENABLED",
        True,
        raising=False,
    )
    await svc.report_usage_for_org(
        _FakeDb(link=None),  # type: ignore[arg-type]
        organization_id=uuid.uuid4(),
        metric_type="LLM_TOKENS",
        quantity=3,
    )


@pytest.mark.asyncio
async def test_downgrade_on_cancel(monkeypatch):
    svc = StripeBillingService()
    org_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    sub = SimpleNamespace(plan_name=SubscriptionPlanName.PRO, status=None)
    customer = SimpleNamespace(
        organization_id=org_id,
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1",
        plan_name="PRO",
        status="active",
    )
    org = SimpleNamespace(
        owner_user_id=owner_id,
        stripe_customer_id="cus_1",
        stripe_subscription_id="sub_1",
        stripe_status="active",
        stripe_plan="PRO",
    )

    class _Db:
        async def scalar(self, _stmt):
            return customer

        async def get(self, _model, _pk):
            return org

        async def flush(self):
            return None

    async def fake_sub(_db, uid):
        return sub

    monkeypatch.setattr(
        "app.services.stripe_billing_service.billing_service._get_or_create_active_subscription",
        fake_sub,
    )
    await svc._downgrade_on_cancel(
        _Db(),  # type: ignore[arg-type]
        {"data": {"object": {"metadata": {"organization_id": str(org_id)}}}},
    )
    assert sub.plan_name == SubscriptionPlanName.FREE
    assert org.stripe_status == "canceled"
