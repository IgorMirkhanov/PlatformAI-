"""QA automation: Integration Hub tenant isolation + webhook DLQ (checklist §§4/7)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.integration_hub import WebhookEventStatus
from app.services.integration_hub.queue import MAX_RETRIES, webhook_retry_countdown


def _make_user(*, org_id: uuid.UUID, role: UserRole = UserRole.OWNER) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.company_id = org_id
    user.organization_id = org_id
    user.role = role
    user.is_superadmin = False
    return user


def _connection(*, org_id: uuid.UUID, connection_id: uuid.UUID | None = None) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=connection_id or uuid.uuid4(),
        organization_id=org_id,
        bot_id=None,
        provider="bitrix24",
        status="connected",
        external_account_id="portal-a",
        config_json={"domain": "acme.bitrix24.ru", "metadata": {"portal": "acme.bitrix24.ru"}},
        oauth_expires_at=None,
        last_error=None,
        updated_at=now,
    )


def _build_hub_app() -> FastAPI:
    from app.api.endpoints.integration_hub import oauth_router, router as hub_router

    app = FastAPI()
    app.include_router(hub_router, prefix="/api/v1")
    app.include_router(oauth_router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_cross_tenant_get_connection_by_id_returns_404() -> None:
    """Workspace B must get 404 for Workspace A's connection id (no existence leak)."""
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    connection_a = _connection(org_id=org_a)
    user_b = _make_user(org_id=org_b)

    app = _build_hub_app()
    db = MagicMock()
    # Workspace-scoped SELECT returns nothing for foreign org.
    db.scalar = AsyncMock(return_value=None)

    async def _override_db() -> AsyncIterator[MagicMock]:
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user_b

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/integrations/connections/{connection_a.id}")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
    db.scalar.assert_awaited()


@pytest.mark.asyncio
async def test_cross_tenant_usage_events_query_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign workspace_id in usage-events query → 403 (strict isolation)."""
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    user_b = _make_user(org_id=org_b)

    app = _build_hub_app()
    db = MagicMock()
    db.scalars = AsyncMock(return_value=MagicMock(all=lambda: []))

    async def _override_db() -> AsyncIterator[MagicMock]:
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user_b

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        forbidden = await client.get(
            "/api/v1/integrations/hub/usage-events",
            params={"workspace_id": str(org_a)},
        )
        own = await client.get(
            "/api/v1/integrations/hub/usage-events",
            params={"workspace_id": str(org_b)},
        )

    app.dependency_overrides.clear()
    assert forbidden.status_code == 403
    assert "workspace" in forbidden.json()["detail"].lower()
    assert own.status_code == 200
    body = own.json()
    assert body["workspace_id"] == str(org_b)
    assert body["events"] == []


def test_dlq_max_retries_and_alert_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failed adapter processing bumps retry_count/backoff, then dead_letter + alert."""
    from app.services.integration_hub import queue as hub_queue
    from app.tasks import hub_queue_tasks

    event_id = uuid.uuid4()
    event = SimpleNamespace(
        id=event_id,
        status=WebhookEventStatus.PROCESSING.value,
        retry_count=0,
        next_retry_at=None,
        error=None,
        processed_at=None,
        provider="bitrix24",
        external_event_id="poison-1",
    )

    class _Session:
        async def get(self, _model: Any, _id: Any) -> SimpleNamespace:
            return event

        async def commit(self) -> None:
            return None

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    class _Factory:
        def __call__(self) -> _Session:
            return _Session()

    alerts: list[dict[str, Any]] = []

    def _alert(**kwargs: Any) -> None:
        alerts.append(kwargs)

    monkeypatch.setattr(hub_queue_tasks, "async_session_factory", _Factory())
    monkeypatch.setattr(
        "app.services.integration_hub.alerts.send_alert_to_monitoring",
        _alert,
    )
    monkeypatch.setattr(hub_queue_tasks, "_hub_webhook_max_retries", lambda: 2)
    monkeypatch.setattr(hub_queue, "MAX_RETRIES", 2)

    async def _boom(_event_id: str) -> dict[str, Any]:
        raise RuntimeError("adapter normalize failed")

    monkeypatch.setattr(hub_queue_tasks, "_consume_webhook_event", _boom)
    monkeypatch.setattr(
        hub_queue_tasks,
        "run_celery_async",
        lambda coro: asyncio.run(coro),
    )

    def _retry_0(*_a: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"celery-retry:{kwargs.get('countdown')}")

    # Attempt 0 → requeue with retry_count=1 + next_retry_at
    hub_queue_tasks.process_hub_webhook_event_task.push_request(retries=0)
    try:
        with pytest.raises(RuntimeError, match="celery-retry:"):
            monkeypatch.setattr(
                hub_queue_tasks.process_hub_webhook_event_task,
                "retry",
                _retry_0,
            )
            hub_queue_tasks.process_hub_webhook_event_task.run(str(event_id))
    finally:
        hub_queue_tasks.process_hub_webhook_event_task.pop_request()

    assert event.retry_count == 1
    assert event.status == WebhookEventStatus.RECEIVED.value
    assert event.next_retry_at is not None
    assert event.next_retry_at > datetime.now(timezone.utc) - timedelta(seconds=1)
    expected_delay = webhook_retry_countdown(1)
    delta = abs(
        (event.next_retry_at - datetime.now(timezone.utc)).total_seconds() - expected_delay
    )
    assert delta < 2
    assert alerts == []

    # Attempt 1 → second requeue (retry_count=2)
    hub_queue_tasks.process_hub_webhook_event_task.push_request(retries=1)
    try:
        with pytest.raises(RuntimeError, match="celery-retry:"):
            monkeypatch.setattr(
                hub_queue_tasks.process_hub_webhook_event_task,
                "retry",
                _retry_0,
            )
            hub_queue_tasks.process_hub_webhook_event_task.run(str(event_id))
    finally:
        hub_queue_tasks.process_hub_webhook_event_task.pop_request()

    assert event.retry_count == 2
    assert event.next_retry_at is not None
    assert event.status == WebhookEventStatus.RECEIVED.value

    # Attempt >= MAX_RETRIES → dead_letter + monitoring alert
    hub_queue_tasks.process_hub_webhook_event_task.push_request(retries=2)
    try:
        result = hub_queue_tasks.process_hub_webhook_event_task.run(str(event_id))
    finally:
        hub_queue_tasks.process_hub_webhook_event_task.pop_request()

    assert result == {"status": "dead_letter", "event_id": str(event_id)}
    assert event.status == WebhookEventStatus.DEAD_LETTER.value
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "critical"
    assert "dead_letter" in alerts[0]["title"].lower()
    assert alerts[0]["details"]["event_id"] == str(event_id)
    assert MAX_RETRIES >= 0
