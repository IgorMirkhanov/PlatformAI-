"""Real-DB CRM lifecycle smoke test against containerized Postgres."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from app.models.core_models import Company, UserCompanyWorkspace, UserRole
from app.models.crm.tag import crm_deal_tags
from app.models.users import User


async def _seed_company(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, User, User]:
    org_id = uuid.uuid4()
    owner = User(
        id=uuid.uuid4(),
        email=f"owner-{org_id.hex[:8]}@crm-real.test",
        hashed_password="!",
        company_name="CRM Real DB",
        full_name="Owner",
        company_id=org_id,
        role=UserRole.OWNER,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )
    operator = User(
        id=uuid.uuid4(),
        email=f"operator-{org_id.hex[:8]}@crm-real.test",
        hashed_password="!",
        company_name="CRM Real DB",
        full_name="Operator",
        company_id=org_id,
        role=UserRole.OPERATOR,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )

    async with factory() as session:
        session.add(owner)
        session.add(operator)
        await session.flush()
        session.add(
            Company(
                id=org_id,
                name="CRM Real DB",
                owner_user_id=owner.id,
                timezone="Asia/Almaty",
            )
        )
        session.add(
            UserCompanyWorkspace(
                user_id=owner.id,
                company_id=org_id,
                role=UserRole.OWNER,
            )
        )
        session.add(
            UserCompanyWorkspace(
                user_id=operator.id,
                company_id=org_id,
                role=UserRole.OPERATOR,
            )
        )
        await session.commit()
    return org_id, owner, operator


def _build_app(
    factory: async_sessionmaker[AsyncSession],
    current: dict[str, User],
) -> FastAPI:
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

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_user() -> User:
        return current["user"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


@pytest.mark.asyncio
async def test_crm_full_lifecycle_real_db(
    real_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, owner, operator = await _seed_company(real_session_factory)
    current: dict[str, User] = {"user": owner}

    ws_updated: list[dict[str, Any]] = []
    partner_webhooks: list[dict[str, Any]] = []

    def _capture_ws_updated(organization_id: uuid.UUID, **kwargs: Any) -> None:
        ws_updated.append({"organization_id": organization_id, **kwargs})

    async def _capture_partner_webhooks(
        db: Any,
        organization_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        partner_webhooks.append(
            {
                "organization_id": organization_id,
                "event_type": event_type,
                "payload": payload,
            }
        )

    monkeypatch.setattr("app.services.crm.crm_ws.publish_deal_updated", _capture_ws_updated)
    monkeypatch.setattr(
        "app.services.crm.webhook_dispatcher_service.notify_partner_webhooks",
        _capture_partner_webhooks,
    )
    monkeypatch.setattr(
        "app.services.crm.deal_service.notify_partner_webhooks",
        _capture_partner_webhooks,
        raising=False,
    )

    app = _build_app(real_session_factory, current)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pipeline = await client.post(
            "/api/v1/crm/pipelines",
            json={"name": "Real DB Sales", "is_default": True},
        )
        assert pipeline.status_code == 201, pipeline.text
        pipeline_id = pipeline.json()["id"]

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
                "name": "Tag on work stage",
                "trigger_type": "stage_entered",
                "trigger_config": {"stage_id": stage_work_id},
                "actions": [{"type": "add_tag", "tag_id": tag_id}],
            },
        )
        assert auto_resp.status_code == 201, auto_resp.text

        wh_resp = await client.post(
            "/api/v1/crm/webhooks",
            json={
                "target_url": "https://partner.example.com/hooks/crm",
                "event_types": ["deal.closed"],
            },
        )
        assert wh_resp.status_code == 201, wh_resp.text

        key_resp = await client.post(
            "/api/v1/crm/api-keys",
            json={"label": "Landing form"},
        )
        assert key_resp.status_code == 201, key_resp.text
        raw_api_key = key_resp.json()["api_key"]

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
        deal_id = lead_resp.json()["deal_id"]

        current["user"] = operator
        assign = await client.patch(
            f"/api/v1/crm/deals/{deal_id}",
            json={"assigned_user_id": str(operator.id)},
        )
        assert assign.status_code == 200, assign.text

        note = await client.post(
            "/api/v1/crm/notes",
            json={"deal_id": deal_id, "text": "Связались с клиентом"},
        )
        assert note.status_code == 201, note.text

        move = await client.post(
            f"/api/v1/crm/deals/{deal_id}/move-stage",
            json={"stage_id": stage_work_id},
        )
        assert move.status_code == 200, move.text

        close = await client.post(
            f"/api/v1/crm/deals/{deal_id}/close",
            json={"status": "won"},
        )
        assert close.status_code == 200, close.text

        current["user"] = owner
        timeline = await client.get(
            "/api/v1/crm/timeline",
            params={"deal_id": deal_id, "limit": 100},
        )
        assert timeline.status_code == 200, timeline.text
        event_types = {event["event_type"] for event in timeline.json()["items"]}
        assert {"deal_created", "stage_changed", "note_added", "tag_added"} <= event_types

        funnel = await client.get(
            "/api/v1/crm/analytics/funnel",
            params={"pipeline_id": pipeline_id},
        )
        assert funnel.status_code == 200, funnel.text
        assert funnel.json()["total_deals"] == 1
        assert funnel.json()["won_deals"] == 1

    async with real_session_factory() as session:
        attached = await session.execute(
            select(crm_deal_tags.c.tag_id).where(crm_deal_tags.c.deal_id == uuid.UUID(deal_id))
        )
        assert uuid.UUID(tag_id) in set(attached.scalars().all())

    assert any(item["event_type"] == "deal.closed" for item in partner_webhooks)
    assert any(str(item.get("stage_id")) == str(stage_work_id) for item in ws_updated)
