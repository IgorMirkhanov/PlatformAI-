"""Tests — AnalyticsService aggregates."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.saas_metering import UsageMetricType
from app.services.analytics_service import AnalyticsService


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return _Result(self.rows)


@pytest.mark.asyncio
async def test_org_summary_aggregates():
    svc = AnalyticsService()
    rows = [
        (UsageMetricType.MESSAGE_IN, 10, 0),
        (UsageMetricType.MESSAGE_OUT, 8, 0),
        (UsageMetricType.LLM_TOKENS, 1500, 12.5),
    ]
    summary = await svc.org_summary(
        _Db(rows),  # type: ignore[arg-type]
        organization_id=uuid.uuid4(),
        days=30,
    )
    assert summary["message_count"] == 18
    assert summary["estimated_cost"] == 12.5
    assert summary["metrics"]["LLM_TOKENS"]["quantity"] == 1500


def test_stripe_meter_payload_shape():
    svc = AnalyticsService()
    payload = svc.stripe_meter_payload(
        stripe_customer_id="cus_1",
        metric=UsageMetricType.LLM_TOKENS,
        quantity=42,
    )
    assert payload["customer"] == "cus_1"
    assert payload["payload"]["value"] == 42
    assert "timestamp" in payload
