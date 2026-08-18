"""CRM WebSocket publish helpers — graceful degradation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.core.websocket import WSEventType
from app.models.crm.deal import DealStatus
from app.schemas.crm.deals import CrmDealRead
from app.services.crm import crm_ws


def _deal_read(org: uuid.UUID) -> CrmDealRead:
    now = datetime.now(timezone.utc)
    return CrmDealRead(
        id=uuid.uuid4(),
        organization_id=org,
        pipeline_id=uuid.uuid4(),
        stage_id=uuid.uuid4(),
        title="Live deal",
        amount=Decimal("100.00"),
        currency="KZT",
        status=DealStatus.OPEN,
        custom_fields={},
        created_at=now,
        updated_at=now,
        closed_at=None,
    )


def test_publish_deal_created_uses_org_as_company_id() -> None:
    org = uuid.uuid4()
    deal = _deal_read(org)
    with patch("app.services.crm.crm_ws.publish_operator_ws_event") as pub:
        crm_ws.publish_deal_created(org, deal, actor_id=uuid.uuid4())
        pub.assert_called_once()
        kwargs = pub.call_args.kwargs
        assert kwargs["company_id"] == str(org)
        assert kwargs["event"] == WSEventType.CRM_DEAL_CREATED.value
        assert kwargs["payload"]["topic"] == "crm"
        assert kwargs["payload"]["type"] == "deal.created"
        assert kwargs["payload"]["deal"]["id"] == str(deal.id)


def test_publish_helpers_never_raise_on_broker_failure() -> None:
    org = uuid.uuid4()
    deal = _deal_read(org)

    def _boom(**_kwargs):
        raise RuntimeError("redis down")

    with patch("app.services.crm.crm_ws.publish_operator_ws_event", side_effect=_boom):
        crm_ws.publish_deal_created(org, deal)
        crm_ws.publish_deal_updated(
            org, deal_id=deal.id, stage_id=deal.stage_id, pipeline_id=deal.pipeline_id
        )
        crm_ws.publish_deal_closed(org, deal_id=deal.id, status="won")


@pytest.mark.asyncio
async def test_create_deal_notifies_ws(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke: deal_service.create path invokes publish without breaking create."""
    from tests.crm.test_deals import FlushSession, _bind_deal_service, _seed_funnel, CrmStore
    from app.schemas.crm.deals import CrmDealCreate

    store = CrmStore()
    service = _bind_deal_service(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed_funnel(store, org)

    called: list[str] = []

    def _capture(organization_id, deal, **_kw):
        called.append(str(deal.id))

    monkeypatch.setattr(
        "app.services.crm.crm_ws.publish_deal_created",
        _capture,
    )

    created = await service.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="WS notify",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
        skip_automations=True,
    )
    assert called == [str(created.id)]
