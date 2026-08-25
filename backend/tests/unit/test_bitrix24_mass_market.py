"""Bitrix24 mass-market adapter: oauth.bitrix.info, portal REST, webhooks, 2 req/s."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services.integration_hub.adapters.bitrix24 import (
    CRM_EVENT_HANDLERS,
    Bitrix24HubAdapter,
    flatten_form_dict,
    parse_bitrix_webhook,
    verify_application_token,
)
from app.services.integration_hub.bitrix_portal import (
    BitrixPortalRateLimited,
    acquire_bitrix_portal_slot,
    portal_rate_key,
)
from app.services.integration_hub.crm_adapter import Bitrix24Adapter
from app.services.integration_hub.oauth import build_authorize_url
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _oauth_secrets() -> TokenBundle:
    return TokenBundle(
        access_token="bx-at",
        refresh_token="bx-rt",
        extra={
            "auth_mode": "oauth",
            "domain": "acme.bitrix24.ru",
            "member_id": "member-aaa",
            "client_endpoint": "https://acme.bitrix24.ru/rest/",
            "application_token": "app-tok",
        },
        external_account_id="member-aaa",
    )


@pytest.fixture
def no_portal_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.bitrix24.acquire_bitrix_portal_slot",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.bitrix24.acquire_bitrix_connection_slot",
        lambda *a, **k: None,
    )


def test_bitrix_authorize_url_always_oauth_bitrix_info() -> None:
    app = PlatformOAuthApp(
        provider="bitrix24",
        client_id="app.123",
        client_secret="secret",
        redirect_uri="https://api.example.com/api/v1/integrations/bitrix24/callback",
    )
    url = build_authorize_url(
        platform_app=app,
        provider="bitrix24",
        state="signed-state",
        extra={"domain": "https://isolated.intranet.local"},
    )
    parsed = urlparse(url)
    assert parsed.netloc == "oauth.bitrix.info"
    assert parsed.path.rstrip("/") == "/oauth/authorize"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["app.123"]
    assert qs["state"] == ["signed-state"]
    assert qs["domain"] == ["isolated.intranet.local"]
    assert "secret" not in url


@pytest.mark.asyncio
async def test_bitrix_code_and_refresh_only_hit_oauth_bitrix_info() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        assert request.url.host == "oauth.bitrix.info"
        assert request.url.path.rstrip("/") == "/oauth/token"
        body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if body.get("grant_type") == "authorization_code":
            assert body["code"] == "auth-code"
            assert body["client_secret"] == "bx-secret"
            return httpx.Response(
                200,
                json={
                    "access_token": "bx-at",
                    "refresh_token": "bx-rt",
                    "expires_in": 3600,
                    "domain": "acme.bitrix24.ru",
                    "member_id": "member-aaa",
                    "client_endpoint": "https://acme.bitrix24.ru/rest/",
                    "application_token": "app-tok",
                },
            )
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "bx-rt"
        return httpx.Response(
            200,
            json={
                "access_token": "bx-at-2",
                "refresh_token": "bx-rt-2",
                "expires_in": 3600,
                "domain": "acme.bitrix24.ru",
                "member_id": "member-aaa",
                "client_endpoint": "https://acme.bitrix24.ru/rest/",
            },
        )

    adapter = Bitrix24HubAdapter()
    platform = PlatformOAuthApp(
        provider="bitrix24",
        client_id="bx-app",
        client_secret="bx-secret",
        redirect_uri="https://api.example.com/callback",
        token_url="https://acme.bitrix24.ru/oauth/token/",
    )
    async with _mock_client(handler) as http:
        bundle = await adapter.connect(
            platform_app=platform,
            payload={"code": "auth-code"},
            http=http,
        )
        refreshed = await adapter.refresh(platform_app=platform, secrets=bundle, http=http)

    assert hosts == ["oauth.bitrix.info", "oauth.bitrix.info"]
    assert bundle.access_token == "bx-at"
    assert bundle.extra.get("member_id") == "member-aaa"
    assert bundle.extra.get("application_token") == "app-tok"
    assert refreshed.access_token == "bx-at-2"
    assert refreshed.extra.get("application_token") == "app-tok"


@pytest.mark.asyncio
async def test_bitrix_event_bind_on_connect_handlers(no_portal_limit: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.bitrix24.resolve_webhook_base_url",
        lambda: "https://hooks.example.com",
    )
    bound: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "acme.bitrix24.ru"
        assert request.url.path.endswith("event.bind")
        body = json.loads(request.content.decode())
        bound.append(body["EVENT"])
        assert "/api/v1/webhooks/bitrix24/" in body["HANDLER"]
        assert body.get("auth") == "bx-at"
        return httpx.Response(200, json={"result": True})

    cid = uuid.uuid4()
    async with _mock_client(handler) as http:
        await Bitrix24HubAdapter().bind_event_handlers(
            secrets=_oauth_secrets(),
            http=http,
            connection_id=cid,
        )
    assert bound == list(CRM_EVENT_HANDLERS)
    assert "ONCRMDEALADD" in bound
    assert "ONCRMCONTACTADD" in bound


def test_bitrix_connect_enqueues_event_bind_queue() -> None:
    import inspect

    from app.services.integration_hub.service import IntegrationHubService

    source = inspect.getsource(IntegrationHubService.connect)
    assert "bind_bitrix24_events_task" in source
    assert "CELERY_CRM_QUEUE" in source


@pytest.mark.asyncio
async def test_bitrix_crm_rest_methods(no_portal_limit: None) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        seen.append(method)
        body = json.loads(request.content.decode())
        if method == "crm.contact.add":
            assert body["fields"]["NAME"] == "Ada"
            return httpx.Response(200, json={"result": 11})
        if method == "crm.contact.update":
            return httpx.Response(200, json={"result": True})
        if method == "crm.contact.list":
            return httpx.Response(200, json={"result": [{"ID": "11", "NAME": "Ada"}]})
        if method == "crm.deal.add":
            return httpx.Response(200, json={"result": 22})
        if method == "crm.deal.update":
            return httpx.Response(200, json={"result": True})
        if method == "crm.deal.list":
            return httpx.Response(200, json={"result": [{"ID": "22", "TITLE": "Lead"}]})
        if method == "crm.dealcategory.stage.list":
            return httpx.Response(200, json={"result": [{"STATUS_ID": "NEW"}]})
        if method == "crm.timeline.comment.add":
            assert body["fields"]["ENTITY_TYPE"] == "deal"
            return httpx.Response(200, json={"result": 3})
        if method == "crm.deal.stage.list":
            pytest.fail("crm.deal.stage.list is not a Bitrix REST method")
        return httpx.Response(404)

    secrets = _oauth_secrets()
    hub = Bitrix24HubAdapter()
    cid = uuid.uuid4()
    async with _mock_client(handler) as http:
        await hub.create_contact(secrets=secrets, http=http, connection_id=cid, name="Ada")
        await hub.update_contact(secrets=secrets, http=http, connection_id=cid, contact_id="11", fields={"NAME": "Ada"})
        await hub.list_contacts(secrets=secrets, http=http, connection_id=cid)
        await hub.create_deal(secrets=secrets, http=http, connection_id=cid, title="Lead")
        await hub.update_deal(secrets=secrets, http=http, connection_id=cid, deal_id="22", fields={"STAGE_ID": "WON"})
        await hub.list_deals(secrets=secrets, http=http, connection_id=cid)
        stages = await hub.list_deal_stages(secrets=secrets, http=http, connection_id=cid)
        await hub.add_note(secrets=secrets, http=http, connection_id=cid, entity_type="deal", entity_id="22", text="hi")
        aliased = await hub.rest_call(
            secrets=secrets, http=http, connection_id=cid, method="crm.deal.stage.list", params={"id": 0}
        )
    assert stages == [{"STATUS_ID": "NEW"}]
    assert aliased == [{"STATUS_ID": "NEW"}]
    assert "crm.contact.add" in seen
    assert "crm.deal.add" in seen
    assert "crm.timeline.comment.add" in seen
    assert "crm.dealcategory.stage.list" in seen
    assert "crm.deal.stage.list" not in seen


def test_bitrix_portal_limiter_is_per_member_id(monkeypatch: pytest.MonkeyPatch) -> None:
    counters: dict[str, int] = {}

    class FakeRedis:
        def incr(self, key: str) -> int:
            counters[key] = counters.get(key, 0) + 1
            return counters[key]

        def expire(self, key: str, ttl: int) -> bool:
            return True

    monkeypatch.setattr(
        "app.services.integration_hub.bitrix_portal.get_redis_client",
        lambda: FakeRedis(),
    )
    portal_a = portal_rate_key("member-a", "a.bitrix24.ru", "conn-1")
    portal_b = portal_rate_key("member-b", "b.bitrix24.ru", "conn-2")
    acquire_bitrix_portal_slot(portal_a, limit=2)
    acquire_bitrix_portal_slot(portal_a, limit=2)
    with pytest.raises(BitrixPortalRateLimited):
        acquire_bitrix_portal_slot(portal_a, limit=2)
    acquire_bitrix_portal_slot(portal_b, limit=2)
    assert portal_a == "member-a"
    assert portal_b == "member-b"


def test_parse_bitrix_form_urlencoded_application_token() -> None:
    nested = flatten_form_dict(
        {
            "event": "ONCRMCONTACTADD",
            "ts": "99",
            "auth[application_token]": "tok-1",
            "auth[member_id]": "member-aaa",
            "data[FIELDS][ID]": "12",
        }
    )
    parsed = parse_bitrix_webhook(nested)
    assert parsed["application_token"] == "tok-1"
    assert parsed["member_id"] == "member-aaa"
    assert parsed["entity_id"] == "12"
    assert verify_application_token(stored="tok-1", provided="tok-1")
    assert not verify_application_token(stored="tok-1", provided="other")


def _json_request(payload: dict) -> MagicMock:
    raw = json.dumps(payload).encode()
    request = MagicMock()
    request.headers.get = lambda name, default=None: "application/json"
    request.body = AsyncMock(return_value=raw)
    request.form = AsyncMock(return_value={})
    return request


@pytest.mark.asyncio
async def test_bitrix_webhook_bad_token_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    cid = uuid.uuid4()
    conn = SimpleNamespace(
        id=cid,
        provider="bitrix24",
        organization_id=uuid.uuid4(),
        credential_id=None,
        config_json={"member_id": "m1"},
        external_account_id="m1",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)
    monkeypatch.setattr(
        "app.services.integration_hub.bitrix_webhook.secrets_from_connection_with_vault",
        AsyncMock(return_value=TokenBundle(extra={"application_token": "stored", "member_id": "m1"})),
    )
    queued: list[object] = []
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.enqueue_hub_webhook_job",
        lambda event_id: queued.append(event_id),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.claim_webhook_dedup_key",
        lambda *a, **k: True,
    )
    from app.services.integration_hub.bitrix_webhook import ingest_bitrix24_webhook

    resp = await ingest_bitrix24_webhook(
        connection_id=cid,
        request=_json_request(
            {
                "event": "ONCRMDEALADD",
                "ts": "1",
                "data": {"FIELDS": {"ID": "9"}},
                "auth": {"application_token": "wrong", "member_id": "m1"},
            }
        ),
        db=db,
    )
    assert resp.status_code == 403
    assert queued == []
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_bitrix_webhook_valid_queues_and_duplicate_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    cid = uuid.uuid4()
    conn = SimpleNamespace(
        id=cid,
        provider="bitrix24",
        organization_id=uuid.uuid4(),
        credential_id=None,
        config_json={"member_id": "m1"},
        external_account_id="m1",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)
    monkeypatch.setattr(
        "app.services.integration_hub.bitrix_webhook.secrets_from_connection_with_vault",
        AsyncMock(return_value=TokenBundle(extra={"application_token": "stored", "member_id": "m1"})),
    )
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
    from app.services.integration_hub.bitrix_webhook import ingest_bitrix24_webhook

    payload = {
        "event": "ONCRMDEALADD",
        "ts": "1",
        "data": {"FIELDS": {"ID": "9"}},
        "auth": {"application_token": "stored", "member_id": "m1"},
    }
    db.scalar = AsyncMock(return_value=uuid.uuid4())
    resp = await ingest_bitrix24_webhook(connection_id=cid, request=_json_request(payload), db=db)
    assert resp.status_code == 200
    assert len(queued) == 1

    queued.clear()
    db.scalar = AsyncMock(return_value=None)
    resp = await ingest_bitrix24_webhook(connection_id=cid, request=_json_request(payload), db=db)
    assert resp.status_code == 200
    assert queued == []


@pytest.mark.asyncio
async def test_bitrix_crm_adapter_create_contact_oauth(no_portal_limit: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("crm.contact.add")
        body = json.loads(request.content.decode())
        assert "PHONE" in body["fields"]
        assert body["auth"] == "bx-at"
        return httpx.Response(200, json={"result": 501})

    adapter = Bitrix24Adapter()
    async with _mock_client(handler) as http:
        contact = await adapter.create_contact(
            secrets=_oauth_secrets(),
            http=http,
            connection_id=uuid.uuid4(),
            name="Ada",
            phone="+7700",
        )
    assert contact.id == "501"
