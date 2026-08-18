"""Tests — usage ledger + stripe meter hook (noop)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.saas_metering import UsageMetricType
from app.services.usage_service import UsageService


class _Db:
    def __init__(self, sub=None):
        self.added = []
        self.sub = sub or SimpleNamespace(id=uuid.uuid4(), balance=Decimal("100.00"), user_id=uuid.uuid4())

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    async def flush(self):
        return None

    async def get(self, model, ident):
        from app.models.core_models import Organization
        from app.models.users import User
        if model is User:
            return SimpleNamespace(id=ident, company_id=ident)
        if model is Organization:
            return SimpleNamespace(id=ident, owner_user_id=ident)
        return None

    async def execute(self, statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.sub, scalar_one=lambda: self.sub)


@pytest.mark.asyncio
async def test_record_and_debit_without_wallet(monkeypatch):
    svc = UsageService()

    async def noop_meter(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.services.stripe_billing_service.stripe_billing_service.report_usage_for_user",
        noop_meter,
    )
    monkeypatch.setattr(
        "app.core.metrics.USAGE_EVENTS",
        SimpleNamespace(labels=lambda **_: SimpleNamespace(inc=lambda: None)),
        raising=False,
    )

    db = _Db()
    event = await svc.record_and_debit(
        db,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        metric_type=UsageMetricType.MESSAGE_IN,
        quantity=1,
        unit_cost=Decimal("0"),
        debit_wallet=False,
    )
    assert event.quantity == 1
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_record_and_debit_wallet(monkeypatch):
    svc = UsageService()
    sub = SimpleNamespace(id=uuid.uuid4(), balance=Decimal("100.00"))

    async def fake_sub(_db, _uid):
        return sub

    async def noop_meter(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.services.billing_service.billing_service._get_or_create_active_subscription",
        fake_sub,
    )
    monkeypatch.setattr(
        "app.services.stripe_billing_service.stripe_billing_service.report_usage_for_user",
        noop_meter,
    )
    monkeypatch.setattr(
        "app.core.metrics.USAGE_EVENTS",
        SimpleNamespace(labels=lambda **_: SimpleNamespace(inc=lambda: None)),
        raising=False,
    )

    db = _Db(sub)
    await svc.record_and_debit(
        db,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        metric_type=UsageMetricType.LLM_TOKENS,
        quantity=10,
        unit_cost=Decimal("0.50"),
        debit_wallet=True,
    )
    assert Decimal(sub.balance) == Decimal("95.00")
    assert len(db.added) == 2  # UsageEvent + BillingTransaction


@pytest.mark.asyncio
async def test_summarize_period():
    svc = UsageService()

    class _Result:
        def all(self):
            return [(UsageMetricType.MESSAGE_IN, 5, 1.0)]

    class _SumDb:
        async def execute(self, _stmt):
            return _Result()

    out = await svc.summarize_period(
        _SumDb(),  # type: ignore[arg-type]
        organization_id=uuid.uuid4(),
        days=7,
    )
    assert out["metrics"]["MESSAGE_IN"]["quantity"] == 5
    assert out["organization_id"] is not None