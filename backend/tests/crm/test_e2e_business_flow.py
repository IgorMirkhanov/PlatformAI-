"""E2E business flow — full CRM lead lifecycle (Inbound → Operator → Close → Analytics)."""

from __future__ import annotations

import sys
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.analytics import router as analytics_router
from app.api.endpoints.crm.api_keys import router as api_keys_router
from app.api.endpoints.crm.automations import router as automations_router
from app.api.endpoints.crm.deals import router as deals_router
from app.api.endpoints.crm.notes import router as notes_router
from app.api.endpoints.crm.pipelines import router as pipelines_router
from app.api.endpoints.crm.public_webhooks import router as public_leads_router
from app.api.endpoints.crm.tags import router as tags_router
from app.api.endpoints.crm.timeline import router as timeline_router
from app.api.endpoints.crm.webhooks import router as webhooks_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.crm.api_key import CrmApiKey
from app.models.crm.automation_rule import AutomationTriggerType
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.users import User
from app.services.crm.api_key_service import ApiKeyService
from app.services.crm.automation_executor_service import AutomationExecutorService
from app.services.crm.automation_rule_service import AutomationRuleService
from app.services.crm.contact_service import ContactService
from app.services.crm.deal_access import CrmActor
from app.services.crm.deal_service import DealService
from app.services.crm.inbound_lead_service import InboundLeadService
from app.services.crm.note_service import NoteService
from app.services.crm.pipeline_service import PipelineService
from app.services.crm.tag_service import TagService
from app.services.crm.timeline_service import TimelineService
from app.services.crm.webhook_subscription_service import WebhookSubscriptionService
from app.services.quota_service import QuotaExceeded, quota_service
from tests.crm.e2e_fakes import (
    FakeAccountRepo,
    FakeAnalyticsRepo,
    FakeApiKeyRepo,
    FakeAutomationRuleRepo,
    FakeContactRepo,
    FakeDealRepo,
    FakeNoteRepo,
    FakePipelineRepo,
    FakeStageRepo,
    FakeTagRepo,
    FakeTimelineRepo,
    FakeWebhookRepo,
    FlushSession,
    Store,
)


def _user(*, org_id: uuid.UUID, role: UserRole, user_id: uuid.UUID | None = None) -> User:
    uid = user_id or uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@e2e.crm.test",
        hashed_password="!",
        company_name="E2E Org",
        full_name=f"{role.value} User",
        company_id=org_id,
        role=role,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


def _bind_e2e(monkeypatch: pytest.MonkeyPatch, store: Store) -> DealService:
    def pipelines(_db: Any, *, organization_id: uuid.UUID) -> FakePipelineRepo:
        return FakePipelineRepo(store, organization_id)

    def contacts(_db: Any, *, organization_id: uuid.UUID) -> FakeContactRepo:
        return FakeContactRepo(store, organization_id)

    def deals(_db: Any, *, organization_id: uuid.UUID, **kw: Any) -> FakeDealRepo:
        return FakeDealRepo(store, organization_id, **kw)

    def rules(_db: Any, *, organization_id: uuid.UUID) -> FakeAutomationRuleRepo:
        return FakeAutomationRuleRepo(store, organization_id)

    def analytics(_db: Any, *, organization_id: uuid.UUID) -> FakeAnalyticsRepo:
        return FakeAnalyticsRepo(store, organization_id)

    tls = TimelineService()
    tls._repo = lambda db, org: FakeTimelineRepo(store, org)  # type: ignore[method-assign]

    pipe_svc = PipelineService()
    pipe_svc._repos = lambda db, org: (  # type: ignore[method-assign]
        FakePipelineRepo(store, org),
        FakeStageRepo(store, org),
    )

    tag_svc = TagService()
    tag_svc._repo = lambda db, org: FakeTagRepo(store, org)  # type: ignore[method-assign]

    note_svc = NoteService()
    note_svc._repo = lambda db, org: FakeNoteRepo(store, org)  # type: ignore[method-assign]

    contact_svc = ContactService()
    contact_svc._contacts = lambda db, org: FakeContactRepo(store, org)  # type: ignore[method-assign]
    contact_svc._accounts = lambda db, org: FakeAccountRepo(store, org)  # type: ignore[method-assign]

    def _deal_repo(
        _db: Any,
        org: uuid.UUID,
        *,
        actor: CrmActor | None = None,
    ) -> FakeDealRepo:
        viewer_user_id = None
        viewer_role = None
        if actor is not None and not actor.sees_all_deals:
            viewer_user_id = actor.user_id
            viewer_role = actor.role
        return FakeDealRepo(
            store, org, viewer_user_id=viewer_user_id, viewer_role=viewer_role
        )

    deal_svc = DealService()
    deal_svc._deals = _deal_repo  # type: ignore[method-assign]
    deal_svc._deals_unscoped = lambda db, org: FakeDealRepo(store, org)  # type: ignore[method-assign]
    deal_svc._pipelines = lambda db, org: FakePipelineRepo(store, org)  # type: ignore[method-assign]
    deal_svc._stages = lambda db, org: FakeStageRepo(store, org)  # type: ignore[method-assign]
    deal_svc._contacts = lambda db, org: FakeContactRepo(store, org)  # type: ignore[method-assign]
    deal_svc._accounts = lambda db, org: FakeAccountRepo(store, org)  # type: ignore[method-assign]

    rule_svc = AutomationRuleService()
    rule_svc._repo = lambda db, org: FakeAutomationRuleRepo(store, org)  # type: ignore[method-assign]

    key_svc = ApiKeyService()
    key_svc._repo = lambda db, org: FakeApiKeyRepo(store, org)  # type: ignore[method-assign]

    wh_svc = WebhookSubscriptionService()
    wh_svc._repo = lambda db, org: FakeWebhookRepo(store, org)  # type: ignore[method-assign]

    executor = AutomationExecutorService()
    executor._rules_repo = lambda db, org: FakeAutomationRuleRepo(store, org)  # type: ignore[method-assign]

    async def _dispatch(
        db: Any,
        organization_id: uuid.UUID,
        trigger_type: AutomationTriggerType,
        deal: CrmDeal,
        *,
        context_extra: dict | None = None,
    ) -> None:
        await executor.run_triggers(db, trigger_type, deal, context_extra=context_extra)

    deal_svc._dispatch_automations = _dispatch  # type: ignore[method-assign]
    inbound = InboundLeadService()

    monkeypatch.setattr(sys.modules["app.services.crm.timeline_service"], "timeline_service", tls)
    monkeypatch.setattr(sys.modules["app.services.crm.pipeline_service"], "pipeline_service", pipe_svc)
    monkeypatch.setattr(sys.modules["app.services.crm.tag_service"], "tag_service", tag_svc)
    monkeypatch.setattr(sys.modules["app.services.crm.tag_service"], "deal_repository", deals)
    monkeypatch.setattr(sys.modules["app.services.crm.tag_service"], "timeline_service", tls)
    monkeypatch.setattr(sys.modules["app.services.crm.note_service"], "note_service", note_svc)
    monkeypatch.setattr(sys.modules["app.services.crm.note_service"], "deal_repository", deals)
    monkeypatch.setattr(sys.modules["app.services.crm.note_service"], "contact_repository", contacts)
    monkeypatch.setattr(sys.modules["app.services.crm.note_service"], "timeline_service", tls)
    monkeypatch.setattr(sys.modules["app.services.crm.contact_service"], "contact_service", contact_svc)
    monkeypatch.setattr(sys.modules["app.services.crm.contact_service"], "contact_repository", contacts)
    monkeypatch.setattr(sys.modules["app.services.crm.deal_service"], "deal_service", deal_svc)
    monkeypatch.setattr(
        sys.modules["app.services.crm.automation_rule_service"],
        "automation_rule_service",
        rule_svc,
    )
    monkeypatch.setattr(sys.modules["app.services.crm.api_key_service"], "api_key_service", key_svc)
    monkeypatch.setattr(
        sys.modules["app.services.crm.webhook_subscription_service"],
        "webhook_subscription_service",
        wh_svc,
    )
    monkeypatch.setattr(
        sys.modules["app.services.crm.automation_executor_service"],
        "automation_executor_service",
        executor,
    )
    monkeypatch.setattr(
        sys.modules["app.services.crm.automation_executor_service"],
        "automation_rule_repository",
        rules,
    )
    monkeypatch.setattr(
        sys.modules["app.services.crm.automation_executor_service"],
        "deal_repository",
        deals,
    )
    monkeypatch.setattr(
        sys.modules["app.services.crm.automation_executor_service"],
        "contact_repository",
        contacts,
    )
    inbound_mod = sys.modules["app.services.crm.inbound_lead_service"]
    monkeypatch.setattr(inbound_mod, "inbound_lead_service", inbound)
    monkeypatch.setattr(inbound_mod, "contact_repository", contacts)
    monkeypatch.setattr(inbound_mod, "pipeline_repository", pipelines)
    monkeypatch.setattr(inbound_mod, "contact_service", contact_svc)
    monkeypatch.setattr(inbound_mod, "deal_service", deal_svc)
    monkeypatch.setattr(
        sys.modules["app.services.crm.crm_analytics_service"],
        "analytics_repository",
        analytics,
    )
    monkeypatch.setattr(
        sys.modules["app.services.crm.webhook_subscription_service"],
        "assert_safe_public_https_url",
        lambda url: url.strip(),
    )

    async def _get_by_hash(_db: Any, digest: str) -> CrmApiKey | None:
        row = store.keys_by_hash.get(digest)
        if row is None or not row.is_active:
            return None
        return row

    monkeypatch.setattr(
        sys.modules["app.services.crm.api_key_service"],
        "get_active_api_key_by_hash",
        _get_by_hash,
    )
    monkeypatch.setattr(
        sys.modules["app.services.crm.api_key_service"],
        "api_key_service",
        key_svc,
    )
    monkeypatch.setattr("app.api.endpoints.crm.deps.api_key_service", key_svc)

    monkeypatch.setattr("app.api.endpoints.crm.pipelines.pipeline_service", pipe_svc)
    monkeypatch.setattr("app.api.endpoints.crm.tags.tag_service", tag_svc)
    monkeypatch.setattr("app.api.endpoints.crm.notes.note_service", note_svc)
    monkeypatch.setattr("app.api.endpoints.crm.deals.deal_service", deal_svc)
    monkeypatch.setattr("app.api.endpoints.crm.deals.tag_service", tag_svc)
    monkeypatch.setattr("app.api.endpoints.crm.timeline.timeline_service", tls)
    monkeypatch.setattr("app.api.endpoints.crm.automations.automation_rule_service", rule_svc)
    monkeypatch.setattr("app.api.endpoints.crm.api_keys.api_key_service", key_svc)
    monkeypatch.setattr("app.api.endpoints.crm.webhooks.webhook_subscription_service", wh_svc)
    monkeypatch.setattr("app.api.endpoints.crm.public_webhooks.inbound_lead_service", inbound)

    from app.services.crm.crm_analytics_service import crm_analytics_service

    monkeypatch.setattr(
        "app.api.endpoints.crm.analytics.crm_analytics_service", crm_analytics_service
    )
    return deal_svc


@pytest.mark.asyncio
async def test_crm_full_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Full lead journey: admin setup → inbound API → operator work →
    automations/WS → close + partner webhook → analytics + quota 402.
    """
    store = Store()
    org_id = uuid.uuid4()
    owner = _user(org_id=org_id, role=UserRole.OWNER)
    operator = _user(org_id=org_id, role=UserRole.OPERATOR)
    current: dict[str, User] = {"user": owner}

    _bind_e2e(monkeypatch, store)

    ws_updated: list[dict[str, Any]] = []
    partner_webhooks: list[dict[str, Any]] = []

    def _capture_ws_updated(organization_id, **kwargs):
        ws_updated.append({"organization_id": organization_id, **kwargs})

    async def _capture_partner_wh(db, organization_id, event_type, payload):
        partner_webhooks.append(
            {"organization_id": organization_id, "event_type": event_type, "payload": payload}
        )

    monkeypatch.setattr("app.services.crm.crm_ws.publish_deal_updated", _capture_ws_updated)
    monkeypatch.setattr(
        "app.services.crm.webhook_dispatcher_service.notify_partner_webhooks",
        _capture_partner_wh,
    )
    monkeypatch.setattr(
        sys.modules["app.services.crm.deal_service"],
        "notify_partner_webhooks",
        _capture_partner_wh,
        raising=False,
    )

    app = FastAPI()
    for router in (
        pipelines_router,
        tags_router,
        automations_router,
        webhooks_router,
        api_keys_router,
        public_leads_router,
        deals_router,
        notes_router,
        timeline_router,
        analytics_router,
    ):
        app.include_router(router, prefix="/api/v1")

    async def _override_user() -> User:
        return current["user"]

    async def _override_db():
        yield FlushSession()

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1 — Admin setup
        current["user"] = owner

        pipe_resp = await client.post(
            "/api/v1/crm/pipelines",
            json={"name": "E2E Sales", "is_default": True},
        )
        assert pipe_resp.status_code == 201, pipe_resp.text
        pipeline_id = pipe_resp.json()["id"]

        stage_new = await client.post(
            f"/api/v1/crm/pipelines/{pipeline_id}/stages",
            json={"name": "Новый", "position": 0},
        )
        assert stage_new.status_code == 201, stage_new.text
        stage_new_id = stage_new.json()["id"]

        stage_work = await client.post(
            f"/api/v1/crm/pipelines/{pipeline_id}/stages",
            json={"name": "В работе", "position": 1},
        )
        assert stage_work.status_code == 201, stage_work.text
        stage_work_id = stage_work.json()["id"]

        tag_resp = await client.post(
            "/api/v1/crm/tags",
            json={"name": "VIP", "color": "#FFD700"},
        )
        assert tag_resp.status_code == 201, tag_resp.text
        tag_id = tag_resp.json()["id"]

        auto_resp = await client.post(
            "/api/v1/crm/automations",
            json={
                "name": "VIP on work stage",
                "trigger_type": "stage_entered",
                "trigger_config": {"stage_id": stage_work_id},
                "actions": [{"type": "add_tag", "tag_id": tag_id}],
            },
        )
        assert auto_resp.status_code == 201, auto_resp.text

        wh_resp = await client.post(
            "/api/v1/crm/webhooks",
            json={
                "target_url": "https://partner.example.com/crm/hooks",
                "event_types": ["deal.closed"],
            },
        )
        assert wh_resp.status_code == 201, wh_resp.text

        key_resp = await client.post("/api/v1/crm/api-keys", json={"label": "Landing form"})
        assert key_resp.status_code == 201, key_resp.text
        raw_api_key = key_resp.json()["api_key"]

        # Step 2 — Inbound lead (API key only)
        lead_resp = await client.post(
            "/api/v1/crm/public/leads",
            headers={"X-CRM-API-Key": raw_api_key},
            json={
                "first_name": "Айгерим",
                "phone": "+77001112233",
                "deal_title": "Лендинг: консультация",
                "pipeline_id": pipeline_id,
                "stage_id": stage_new_id,
            },
        )
        assert lead_resp.status_code == 201, lead_resp.text
        lead_body = lead_resp.json()
        deal_id = uuid.UUID(str(lead_body["deal_id"]))
        contact_id = uuid.UUID(str(lead_body["contact_id"]))

        assert contact_id in store.contacts
        assert deal_id in store.deals
        assert store.deals[deal_id].stage_id == uuid.UUID(stage_new_id)
        assert store.deals[deal_id].status == DealStatus.OPEN
        assert store.deals[deal_id].title == "Лендинг: консультация"

        # Step 3 — Operator RBAC + work
        current["user"] = operator

        listed = await client.get("/api/v1/crm/deals", params={"pipeline_id": pipeline_id})
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] >= 1
        assert any(str(i["id"]) == str(deal_id) for i in listed.json()["items"])

        assign = await client.patch(
            f"/api/v1/crm/deals/{deal_id}",
            json={"assigned_user_id": str(operator.id)},
        )
        assert assign.status_code == 200, assign.text
        assert assign.json()["assigned_user_id"] == str(operator.id)

        note = await client.post(
            "/api/v1/crm/notes",
            json={"deal_id": str(deal_id), "text": "Связались с клиентом, ждём КП"},
        )
        assert note.status_code == 201, note.text

        move = await client.post(
            f"/api/v1/crm/deals/{deal_id}/move-stage",
            json={"stage_id": stage_work_id},
        )
        assert move.status_code == 200, move.text
        assert move.json()["stage_id"] == stage_work_id

        # Step 4 — Automations + timeline + WS (timeline is OWNER/ADMIN)
        current["user"] = owner
        timeline = await client.get(
            "/api/v1/crm/timeline",
            params={"deal_id": str(deal_id), "limit": 100},
        )
        assert timeline.status_code == 200, timeline.text
        event_types = {e["event_type"] for e in timeline.json()["items"]}
        assert "deal_created" in event_types
        assert "stage_changed" in event_types
        assert "note_added" in event_types
        assert (deal_id, uuid.UUID(tag_id)) in store.deal_tags
        assert "tag_added" in event_types

        assert any(
            str(c.get("deal_id")) == str(deal_id)
            and str(c.get("stage_id")) == str(stage_work_id)
            for c in ws_updated
        ), f"expected deal.updated WS publish, got {ws_updated}"

        # Step 5 — Close + webhook + analytics + quota 402
        current["user"] = operator
        close = await client.post(
            f"/api/v1/crm/deals/{deal_id}/close",
            json={"status": "won"},
        )
        assert close.status_code == 200, close.text
        assert close.json()["status"] == "won"
        assert store.deals[deal_id].status == DealStatus.WON

        assert any(w["event_type"] == "deal.closed" for w in partner_webhooks), (
            f"expected partner webhook deal.closed, got {partner_webhooks}"
        )

        current["user"] = owner
        funnel = await client.get(
            "/api/v1/crm/analytics/funnel",
            params={"pipeline_id": pipeline_id},
        )
        assert funnel.status_code == 200, funnel.text
        funnel_body = funnel.json()
        assert funnel_body["total_deals"] == 1
        assert funnel_body["won_deals"] == 1
        assert funnel_body["conversion_rate"] == pytest.approx(1.0)

        async def _block_open_deals(*_a: Any, **_k: Any) -> None:
            raise QuotaExceeded(
                "crm_deals_open_limit",
                "Plan FREE allows 0 open CRM deal(s). Upgrade billing to add more.",
            )

        monkeypatch.setattr(quota_service, "assert_crm_deals_open_quota", _block_open_deals)

        blocked = await client.post(
            "/api/v1/crm/deals",
            json={
                "title": "Should fail quota",
                "pipeline_id": pipeline_id,
                "stage_id": stage_new_id,
            },
        )
        assert blocked.status_code == 402, blocked.text
        detail = blocked.json()["detail"]
        assert detail["code"] == "crm_deals_open_limit"
        assert detail["billing_url"] == "/billing"

    assert len(store.contacts) == 1
    assert len(store.deals) == 1
