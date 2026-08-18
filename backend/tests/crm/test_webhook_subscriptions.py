"""Native CRM Phase C step 3 — outbound webhook subscriptions."""

from __future__ import annotations

import hashlib
import hmac
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.webhooks import router as webhooks_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.crm.webhook_subscription import CrmWebhookSubscription
from app.models.users import User
from app.schemas.crm.webhooks import (
    CrmWebhookSubscriptionCreate,
    CrmWebhookSubscriptionUpdate,
)
from app.services.crm.webhook_dispatcher_service import (
    SIGNATURE_HEADER,
    build_webhook_body,
    enqueue_partner_webhook,
    sign_webhook_payload,
    webhook_dispatcher_service,
)
from app.services.crm.webhook_subscription_service import (
    WebhookSubscriptionService,
    WebhookSubscriptionServiceError,
    generate_webhook_secret,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(*, org_id: uuid.UUID) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@crm.test",
        hashed_password="!",
        company_name="Org",
        full_name="Webhook Tester",
        company_id=org_id,
        role=UserRole.OWNER,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


class Store:
    def __init__(self) -> None:
        self.subs: dict[uuid.UUID, CrmWebhookSubscription] = {}


class FlushSession:
    async def flush(self) -> None:
        return None


class FakeWebhookRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmWebhookSubscription) -> CrmWebhookSubscription:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.event_types = list(getattr(entity, "event_types", None) or [])
        self.store.subs[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmWebhookSubscription | None:
        row = self.store.subs.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def list_ordered(self, *, limit: int = 100, offset: int = 0) -> list[CrmWebhookSubscription]:
        rows = [s for s in self.store.subs.values() if s.organization_id == self.organization_id]
        rows = sorted(rows, key=lambda s: s.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def count_all(self) -> int:
        return len([s for s in self.store.subs.values() if s.organization_id == self.organization_id])

    async def delete(self, entity: CrmWebhookSubscription) -> None:
        self.store.subs.pop(entity.id, None)

    async def list_active_for_event(self, event_type: str) -> list[CrmWebhookSubscription]:
        out = []
        for s in self.store.subs.values():
            if s.organization_id != self.organization_id or not s.is_active:
                continue
            types = list(s.event_types or [])
            if event_type in types or "*" in types:
                out.append(s)
        return out


def _bind(monkeypatch: pytest.MonkeyPatch, store: Store) -> WebhookSubscriptionService:
    def _factory(_db: Any, *, organization_id: uuid.UUID) -> FakeWebhookRepo:
        return FakeWebhookRepo(store, organization_id)

    mod = sys.modules["app.services.crm.webhook_subscription_service"]
    monkeypatch.setattr(mod, "webhook_subscription_repository", _factory, raising=False)
    disp = sys.modules["app.services.crm.webhook_dispatcher_service"]
    monkeypatch.setattr(disp, "webhook_subscription_repository", _factory, raising=False)

    # Avoid real DNS during unit tests; SSRF cases still hit the real guard.
    def _allow(url: str) -> str:
        return url.strip()

    monkeypatch.setattr(mod, "assert_safe_public_https_url", _allow)
    monkeypatch.setattr(disp, "assert_safe_public_https_url", _allow)

    service = WebhookSubscriptionService()
    service._repo = lambda db, organization_id: FakeWebhookRepo(store, organization_id)  # type: ignore[method-assign]
    mod.webhook_subscription_service = service
    return service


@pytest.mark.asyncio
async def test_crud_and_tenant_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    service = _bind(monkeypatch, store)
    db = FlushSession()

    created = await service.create_subscription(
        db,  # type: ignore[arg-type]
        org_a,
        CrmWebhookSubscriptionCreate(
            target_url="https://partner.example.com/hooks/crm",
            event_types=["deal.created", "deal.closed"],
        ),
    )
    assert created.organization_id == org_a
    assert len(created.secret) == 64  # token_hex(32)
    assert "deal.created" in created.event_types

    listed_a = await service.list_subscriptions(db, org_a)  # type: ignore[arg-type]
    assert listed_a.total == 1

    listed_b = await service.list_subscriptions(db, org_b)  # type: ignore[arg-type]
    assert listed_b.total == 0

    with pytest.raises(WebhookSubscriptionServiceError) as exc:
        await service.get_subscription(db, org_b, created.id)  # type: ignore[arg-type]
    assert exc.value.status_code == 404

    updated = await service.update_subscription(
        db,  # type: ignore[arg-type]
        org_a,
        created.id,
        CrmWebhookSubscriptionUpdate(is_active=False),
    )
    assert updated.is_active is False

    await service.delete_subscription(db, org_a, created.id)  # type: ignore[arg-type]
    assert listed_a.total == 1  # stale snapshot
    after = await service.list_subscriptions(db, org_a)  # type: ignore[arg-type]
    assert after.total == 0


@pytest.mark.asyncio
async def test_create_rejects_ssrf_url(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    # Bind repos only — keep real SSRF guard for this test.
    def _factory(_db: Any, *, organization_id: uuid.UUID) -> FakeWebhookRepo:
        return FakeWebhookRepo(store, organization_id)

    mod = sys.modules["app.services.crm.webhook_subscription_service"]
    monkeypatch.setattr(mod, "webhook_subscription_repository", _factory, raising=False)
    service = WebhookSubscriptionService()
    service._repo = lambda db, organization_id: FakeWebhookRepo(store, organization_id)  # type: ignore[method-assign]

    with pytest.raises(WebhookSubscriptionServiceError) as exc:
        await service.create_subscription(
            FlushSession(),  # type: ignore[arg-type]
            uuid.uuid4(),
            CrmWebhookSubscriptionCreate(
                target_url="https://127.0.0.1/hook",
                event_types=["deal.created"],
            ),
        )
    assert exc.value.status_code == 400


def test_hmac_signature_matches_payload() -> None:
    secret = "test-secret-value-32chars-minimum!"
    body = build_webhook_body("deal.created", {"id": "abc", "title": "Lead"})
    header = sign_webhook_payload(secret=secret, body=body)
    assert header.startswith("sha256=")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert header == f"sha256={expected}"


@pytest.mark.asyncio
async def test_dispatcher_sends_signed_header(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    _bind(monkeypatch, store)
    secret = generate_webhook_secret()
    sub = CrmWebhookSubscription(
        id=uuid.uuid4(),
        organization_id=org,
        target_url="https://hooks.example.com/crm",
        event_types=["deal.created"],
        secret=secret,
        is_active=True,
        created_at=_now(),
        updated_at=_now(),
    )
    store.subs[sub.id] = sub

    captured: dict[str, Any] = {}

    class _Resp:
        status_code = 200

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, url: str, content: bytes = b"", headers: dict | None = None):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers or {}
            return _Resp()

    monkeypatch.setattr(
        "app.services.crm.webhook_dispatcher_service.httpx.AsyncClient",
        lambda **_kw: _Client(),
    )

    results = await webhook_dispatcher_service.dispatch_event(
        FlushSession(),  # type: ignore[arg-type]
        org,
        "deal.created",
        {"deal_id": str(uuid.uuid4())},
    )
    assert len(results) == 1
    assert results[0]["ok"] is True
    sig = captured["headers"].get(SIGNATURE_HEADER)
    assert sig == sign_webhook_payload(secret=secret, body=captured["content"])
    assert captured["headers"].get("X-CRM-Event") == "deal.created"


@pytest.mark.asyncio
async def test_dispatcher_blocks_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()

    def _factory(_db: Any, *, organization_id: uuid.UUID) -> FakeWebhookRepo:
        return FakeWebhookRepo(store, organization_id)

    disp = sys.modules["app.services.crm.webhook_dispatcher_service"]
    monkeypatch.setattr(disp, "webhook_subscription_repository", _factory, raising=False)
    # Keep real SSRF guard (do not stub assert_safe_public_https_url).

    sub = CrmWebhookSubscription(
        id=uuid.uuid4(),
        organization_id=org,
        target_url="https://192.168.1.10/internal",
        event_types=["*"],
        secret=generate_webhook_secret(),
        is_active=True,
        created_at=_now(),
        updated_at=_now(),
    )
    store.subs[sub.id] = sub

    posted = {"n": 0}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, *_a, **_k):
            posted["n"] += 1
            raise AssertionError("must not POST to private IP")

    monkeypatch.setattr(
        "app.services.crm.webhook_dispatcher_service.httpx.AsyncClient",
        lambda **_kw: _Client(),
    )

    results = await webhook_dispatcher_service.dispatch_event(
        FlushSession(),  # type: ignore[arg-type]
        org,
        "deal.updated",
        {"x": 1},
    )
    assert posted["n"] == 0
    assert results[0]["ok"] is False
    assert "ssrf_blocked" in results[0]["error"]


def test_enqueue_partner_webhook_calls_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    class _Task:
        def apply_async(self, **kwargs):
            called.update(kwargs)
            return MagicMock(id="task-1")

    monkeypatch.setattr(
        "app.tasks.crm_tasks.dispatch_webhook_task",
        _Task(),
        raising=False,
    )
    # enqueue imports from app.tasks.crm_tasks inside the function
    import app.tasks.crm_tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "dispatch_webhook_task", _Task())

    org = uuid.uuid4()
    ok = enqueue_partner_webhook(
        organization_id=org,
        event_type="contact.created",
        payload={"id": "1"},
    )
    assert ok is True
    assert called["kwargs"]["organization_id_str"] == str(org)
    assert called["kwargs"]["event_type"] == "contact.created"


@pytest.mark.asyncio
async def test_dispatch_webhook_task_async_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import crm_webhook_tasks as wh_mod

    org = uuid.uuid4()
    mock_dispatch = AsyncMock(return_value=[{"ok": True}])
    monkeypatch.setattr(webhook_dispatcher_service, "dispatch_event", mock_dispatch)

    class _Cm:
        async def __aenter__(self):
            return FlushSession()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(wh_mod, "async_session_factory", lambda: _Cm())

    result = await wh_mod._dispatch_webhook_async(org, "deal.closed", {"status": "won"})
    assert result["success"] is True
    assert result["event_type"] == "deal.closed"
    mock_dispatch.assert_awaited()


def test_enqueue_registers_celery_task_name() -> None:
    from app.workers.crm_webhook_tasks import dispatch_webhook_task

    assert dispatch_webhook_task.name == "app.tasks.crm_tasks.dispatch_webhook_task"


@pytest.mark.asyncio
async def test_webhooks_api_crud(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    user = _make_user(org_id=org)
    service = _bind(monkeypatch, store)

    app = FastAPI()
    app.include_router(webhooks_router, prefix="/api/v1")

    async def _user() -> User:
        return user

    async def _db():
        yield FlushSession()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(
        "app.api.endpoints.crm.webhooks.webhook_subscription_service",
        service,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/crm/webhooks",
            json={
                "target_url": "https://partner.example.com/hook",
                "event_types": ["deal.created"],
            },
        )
        assert created.status_code == 201
        body = created.json()
        sub_id = body["id"]
        assert body["secret"]

        listed = await client.get("/api/v1/crm/webhooks")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        patched = await client.patch(
            f"/api/v1/crm/webhooks/{sub_id}",
            json={"is_active": False},
        )
        assert patched.status_code == 200
        assert patched.json()["is_active"] is False

        deleted = await client.delete(f"/api/v1/crm/webhooks/{sub_id}")
        assert deleted.status_code == 204
