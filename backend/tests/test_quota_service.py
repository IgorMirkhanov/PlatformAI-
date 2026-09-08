"""Tests — quota enforcement helpers (organization-scoped)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.core_models import SubscriptionPlanName
from app.services.quota_service import QuotaExceeded, QuotaService


class _Db:
    def __init__(self, *, count: int = 0):
        self.count = count

    async def scalar(self, _stmt):
        return self.count

    async def get(self, _model, _pk):
        return None


@pytest.mark.asyncio
async def test_plan_from_stripe_customer(monkeypatch):
    svc = QuotaService()
    org_id = uuid.uuid4()
    customer = SimpleNamespace(plan_name="ENTERPRISE")

    class _Db:
        async def scalar(self, _stmt):
            return customer

        async def get(self, _model, _pk):
            return None

    plan = await svc._plan(_Db(), org_id)  # type: ignore[arg-type]
    assert plan == SubscriptionPlanName.ENTERPRISE


@pytest.mark.asyncio
async def test_bots_quota_blocks(monkeypatch):
    svc = QuotaService()

    async def fake_plan(_db, _oid):
        return SubscriptionPlanName.FREE

    monkeypatch.setattr(svc, "_plan", fake_plan)
    db = _Db(count=999)
    with pytest.raises(QuotaExceeded) as exc:
        await svc.assert_can_create_bot(db, uuid.uuid4())  # type: ignore[arg-type]
    assert exc.value.code == "bots_limit"


@pytest.mark.asyncio
async def test_message_quota_ok(monkeypatch):
    svc = QuotaService()

    async def fake_plan(_db, _oid):
        return SubscriptionPlanName.PRO

    monkeypatch.setattr(svc, "_plan", fake_plan)
    db = _Db(count=10)
    await svc.assert_message_quota(db, uuid.uuid4())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_message_quota_blocks(monkeypatch):
    svc = QuotaService()

    async def fake_plan(_db, _oid):
        return SubscriptionPlanName.FREE

    monkeypatch.setattr(svc, "_plan", fake_plan)
    db = _Db(count=200)
    with pytest.raises(QuotaExceeded) as exc:
        await svc.assert_message_quota(db, uuid.uuid4())  # type: ignore[arg-type]
    assert exc.value.code == "messages_day_limit"


@pytest.mark.asyncio
async def test_token_quota_blocks(monkeypatch):
    svc = QuotaService()

    async def fake_plan(_db, _oid):
        return SubscriptionPlanName.FREE

    monkeypatch.setattr(svc, "_plan", fake_plan)
    db = _Db(count=100_000)
    with pytest.raises(QuotaExceeded) as exc:
        await svc.assert_token_quota(db, uuid.uuid4(), upcoming_tokens=1)  # type: ignore[arg-type]
    assert exc.value.code == "tokens_month_limit"


def test_raise_http_maps_402():
    svc = QuotaService()
    with pytest.raises(HTTPException) as exc:
        svc.raise_http(QuotaExceeded("bots_limit", "upgrade"))
    assert exc.value.status_code == 402
    assert exc.value.detail["billing_url"] == "/billing"
