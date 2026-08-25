"""amoCRM adapter: one-time refresh lock, 7 req/s throttle, webhooks, CRM methods."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.integration_hub.adapters.amocrm import (
    WEBHOOK_EVENTS,
    AmoCRMHubAdapter,
    parse_amocrm_webhook,
)
from app.services.integration_hub.amocrm_account import (
    AmoCRMAccountRateLimited,
    acquire_amocrm_account_slot,
    account_rate_key,
)
from app.services.integration_hub.crm_adapter import AmoCRMAdapter
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _secrets() -> TokenBundle:
    return TokenBundle(
        access_token="at",
        refresh_token="rt-old",
        extra={"subdomain": "acme.amocrm.ru", "account_id": "42"},
        external_account_id="acme.amocrm.ru",
    )


@pytest.fixture
def no_account_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.amocrm.acquire_amocrm_account_slot",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.amocrm.acquire_amocrm_connection_slot",
        lambda *a, **k: None,
    )


def test_amocrm_connect_enqueues_webhook_subscribe() -> None:
    import inspect

    from app.services.integration_hub.service import IntegrationHubService

    source = inspect.getsource(IntegrationHubService.connect)
    assert "bind_amocrm_webhooks_task" in source


@pytest.mark.asyncio
async def test_amocrm_bind_webhooks_on_connect(no_account_limit: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.amocrm.resolve_webhook_base_url",
        lambda: "https://hooks.example.com",
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"destination": captured["body"]["destination"]})

    cid = uuid.uuid4()
    async with _mock_client(handler) as http:
        await AmoCRMHubAdapter().bind_event_handlers(secrets=_secrets(), http=http, connection_id=cid)

    assert str(captured["url"]).endswith("/api/v4/webhooks")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["destination"] == f"https://hooks.example.com/api/v1/webhooks/amocrm/{cid}"
    for event in ("add_lead", "update_lead", "add_contact", "update_contact"):
        assert event in body["settings"]
    assert set(WEBHOOK_EVENTS).issubset(set(body["settings"]))


@pytest.mark.asyncio
async def test_amocrm_crm_methods(no_account_limit: None) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/api/v4/contacts") and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"contacts": [{"id": 11}]}})
        if request.url.path.endswith("/api/v4/contacts") and request.method == "PATCH":
            return httpx.Response(200, json={"_embedded": {"contacts": [{"id": 11}]}})
        if request.url.path.endswith("/api/v4/contacts") and request.method == "GET":
            return httpx.Response(200, json={"_embedded": {"contacts": [{"id": 11, "name": "Ada"}]}})
        if request.url.path.endswith("/api/v4/leads") and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"leads": [{"id": 22}]}})
        if request.url.path.endswith("/api/v4/leads") and request.method == "PATCH":
            return httpx.Response(200, json={"_embedded": {"leads": [{"id": 22}]}})
        if "/notes" in request.url.path:
            return httpx.Response(200, json={"_embedded": {"notes": [{"id": 3}]}})
        return httpx.Response(404)

    adapter = AmoCRMAdapter()
    cid = uuid.uuid4()
    secrets = _secrets()
    async with _mock_client(handler) as http:
        contact = await adapter.create_contact(
            secrets=secrets, http=http, connection_id=cid, name="Ada", phone="+7700"
        )
        found = await adapter.find_contact(secrets=secrets, http=http, connection_id=cid, phone="+7700")
        await adapter.update_contact(secrets=secrets, http=http, connection_id=cid, contact_id="11", name="Ada")
        deal = await adapter.create_deal(
            secrets=secrets, http=http, connection_id=cid, title="Lead", contact_id="11"
        )
        await adapter.update_deal_stage(
            secrets=secrets, http=http, connection_id=cid, deal_id="22", stage_id="142"
        )
        await adapter.add_note(
            secrets=secrets, http=http, connection_id=cid, entity_type="deal", entity_id="22", text="hi"
        )
    assert contact.id == "11"
    assert found is not None and found.id == "11"
    assert deal.id == "22"
    assert ("POST", "/api/v4/contacts") in seen
    assert ("PATCH", "/api/v4/leads") in seen
    assert any(path.endswith("/notes") for _, path in seen)


@pytest.mark.asyncio
async def test_amocrm_429_retries_with_exponential_backoff(
    no_account_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.services.integration_hub.adapters.amocrm.asyncio.sleep", fake_sleep)
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"_embedded": {"contacts": [{"id": 7}]}})

    async with _mock_client(handler) as http:
        result = await AmoCRMHubAdapter().create_contact(
            secrets=_secrets(), http=http, connection_id=uuid.uuid4(), name="Ada"
        )
    assert result["id"] == "7"
    assert hits["n"] == 3
    assert sleeps == [2.0, 2.0]


def test_amocrm_account_limiter_is_per_subdomain(monkeypatch: pytest.MonkeyPatch) -> None:
    counters: dict[str, int] = {}

    class FakeRedis:
        def incr(self, key: str) -> int:
            counters[key] = counters.get(key, 0) + 1
            return counters[key]

        def expire(self, key: str, ttl: int) -> bool:
            return True

    monkeypatch.setattr(
        "app.services.integration_hub.amocrm_account.get_redis_client",
        lambda: FakeRedis(),
    )
    a = account_rate_key("acme.amocrm.ru", "c1")
    b = account_rate_key("other.amocrm.ru", "c2")
    for _ in range(7):
        acquire_amocrm_account_slot(a, limit=7)
    with pytest.raises(AmoCRMAccountRateLimited):
        acquire_amocrm_account_slot(a, limit=7)
    acquire_amocrm_account_slot(b, limit=7)


@pytest.mark.asyncio
async def test_refresh_connection_skips_when_token_already_rotated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.integration_hub.service.pg_advisory_xact_lock_hashtext",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.service.pg_advisory_xact_lock_uuid",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.service.decrypt_payload",
        lambda *a, **k: {
            "access_token": "at-new",
            "refresh_token": "rt-new",
            "subdomain": "acme.amocrm.ru",
        },
    )
    conn = SimpleNamespace(
        id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
        provider="amocrm",
        oauth_expires_at=None,
    )
    cred = SimpleNamespace(
        id=conn.credential_id,
        encrypted_payload=b"x",
        encryption_iv=b"y",
        encryption_tag=b"z",
        key_version=1,
    )
    seen = {"n": 0}

    async def scalar(_stmt):
        seen["n"] += 1
        return conn if seen["n"] == 1 else cred

    db = AsyncMock()
    db.scalar = scalar
    refresh_http = AsyncMock()
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.amocrm.AmoCRMHubAdapter.refresh",
        refresh_http,
    )

    from app.services.integration_hub.service import integration_hub_service

    result = await integration_hub_service.refresh_connection(
        db, conn, expected_refresh_token="rt-old"
    )
    assert result is conn
    refresh_http.assert_not_called()


def test_parse_amocrm_webhook_leads_and_contacts() -> None:
    parsed = parse_amocrm_webhook(
        {
            "leads": {"add": [{"id": "88", "updated_at": "1"}]},
            "contacts": {"update": {"0": {"id": "11", "last_modified": "2"}}},
            "account": {"subdomain": "acme"},
        }
    )
    assert parsed["subdomain"] == "acme"
    ids = {(e["entity"], e["action"], e["entity_id"]) for e in parsed["events"]}
    assert ("leads", "add", "88") in ids
    assert ("contacts", "update", "11") in ids


def _json_request(payload: dict) -> MagicMock:
    raw = json.dumps(payload).encode()
    request = MagicMock()
    request.headers.get = lambda name, default=None: "application/json"
    request.body = AsyncMock(return_value=raw)
    request.form = AsyncMock(return_value={})
    return request


@pytest.mark.asyncio
async def test_amocrm_webhook_account_mismatch_is_403() -> None:
    cid = uuid.uuid4()
    conn = SimpleNamespace(
        id=cid,
        provider="amocrm",
        organization_id=uuid.uuid4(),
        config_json={"subdomain": "acme.amocrm.ru"},
        external_account_id="acme.amocrm.ru",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)
    from app.services.integration_hub.amocrm_webhook import ingest_amocrm_webhook

    resp = await ingest_amocrm_webhook(
        connection_id=cid,
        request=_json_request(
            {
                "leads": {"add": [{"id": "1"}]},
                "account": {"subdomain": "other"},
            }
        ),
        db=db,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_amocrm_webhook_valid_queues_and_duplicate_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    cid = uuid.uuid4()
    conn = SimpleNamespace(
        id=cid,
        provider="amocrm",
        organization_id=uuid.uuid4(),
        config_json={"subdomain": "acme.amocrm.ru"},
        external_account_id="acme.amocrm.ru",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)
    queued: list[object] = []
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.enqueue_hub_webhook_job",
        lambda event_id: queued.append(event_id),
    )
    claims = {"n": 0}

    def _claim(*_a, **_k):
        claims["n"] += 1
        return claims["n"] == 1

    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.claim_webhook_dedup_key",
        _claim,
    )
    from app.services.integration_hub.amocrm_webhook import ingest_amocrm_webhook

    payload = {
        "leads": {"add": [{"id": "88", "updated_at": "1"}]},
        "account": {"subdomain": "acme"},
    }
    db.scalar = AsyncMock(return_value=uuid.uuid4())
    resp = await ingest_amocrm_webhook(connection_id=cid, request=_json_request(payload), db=db)
    assert resp.status_code == 200
    assert len(queued) == 1

    queued.clear()
    db.scalar = AsyncMock(return_value=None)
    resp = await ingest_amocrm_webhook(connection_id=cid, request=_json_request(payload), db=db)
    assert resp.status_code == 200
    assert queued == []
