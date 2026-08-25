"""Integration Hub adapters, rate limit, envelope crypto, webhook ingest order."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import Response

from app.services.crypto_service import decrypt_field, encrypt_field
from app.services.integration_hub.adapters import get_hub_adapter
from app.services.integration_hub.adapters.amocrm import AmoCRMHubAdapter
from app.services.integration_hub.adapters.bitrix24 import Bitrix24HubAdapter
from app.services.integration_hub.adapters.kaspi import KaspiPayHubAdapter
from app.services.integration_hub.adapters.wazzup import WazzupHubAdapter
from app.services.integration_hub.adapters.whatsapp import WhatsAppHubAdapter
from app.services.integration_hub.rate_limit import ConnectionRateLimited, acquire_connection_slot
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle
from app.services.webhooks.router_service import ingest_provider_webhook


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_amocrm_connect_uses_platform_secret_not_tenant() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"id": 42, "name": "Acme"})
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        )

    adapter = AmoCRMHubAdapter()
    platform = PlatformOAuthApp(
        provider="amocrm",
        client_id="platform-client",
        client_secret="platform-secret",
        redirect_uri="https://app.example.com/callback",
    )
    async with _mock_client(handler) as http:
        bundle = await adapter.connect(
            platform_app=platform,
            payload={
                "subdomain": "acme",
                "authorization_code": "auth-code-1",
                "client_secret": "tenant-must-not-be-sent",
            },
            http=http,
        )

    assert captured["body"]["client_secret"] == "platform-secret"
    assert captured["body"]["client_id"] == "platform-client"
    assert "tenant-must-not-be-sent" not in json.dumps(captured["body"])
    assert bundle.access_token == "new-access"
    assert bundle.refresh_token == "new-refresh"
    assert bundle.external_account_id == "acme.amocrm.ru"
    assert bundle.extra.get("account_id") == "42"


@pytest.mark.asyncio
async def test_amocrm_refresh_exchanges_one_time_refresh_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "rt-old"
        assert body["client_secret"] == "platform-secret"
        return httpx.Response(
            200,
            json={"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 7200},
        )

    adapter = AmoCRMHubAdapter()
    platform = PlatformOAuthApp(
        provider="amocrm",
        client_id="cid",
        client_secret="platform-secret",
        redirect_uri="https://app.example.com/callback",
    )
    async with _mock_client(handler) as http:
        bundle = await adapter.refresh(
            platform_app=platform,
            secrets=TokenBundle(
                access_token="at-old",
                refresh_token="rt-old",
                extra={"subdomain": "acme.amocrm.ru"},
                external_account_id="acme.amocrm.ru",
            ),
            http=http,
        )
    assert bundle.access_token == "at-new"
    assert bundle.refresh_token == "rt-new"


@pytest.mark.asyncio
async def test_bitrix24_oauth_connect_and_webhook() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.path.endswith("/oauth/token/"):
            assert request.url.host == "oauth.bitrix.info"
            return httpx.Response(
                200,
                json={
                    "access_token": "bx-at",
                    "refresh_token": "bx-rt",
                    "expires_in": 3600,
                    "domain": "acme.bitrix24.ru",
                },
            )
        if request.url.path.endswith("/profile.json"):
            return httpx.Response(200, json={"result": {"ID": 1}})
        return httpx.Response(404)

    adapter = Bitrix24HubAdapter()
    platform = PlatformOAuthApp(
        provider="bitrix24",
        client_id="bx-app",
        client_secret="bx-secret",
        token_url="https://oauth.bitrix.info/oauth/token/",
    )
    async with _mock_client(handler) as http:
        oauth = await adapter.connect(
            platform_app=platform,
            payload={"code": "auth-code"},
            http=http,
        )
        hook = await adapter.connect(
            platform_app=platform,
            payload={"webhook_url": "https://acme.bitrix24.ru/rest/1/hooktoken"},
            http=http,
        )
    assert oauth.access_token == "bx-at"
    assert oauth.refresh_token == "bx-rt"
    assert hook.webhook_url.endswith("/")
    assert (hook.extra or {}).get("auth_mode") == "webhook"
    assert "oauth.bitrix.info" in hosts


@pytest.mark.asyncio
async def test_wazzup_and_kaspi_connect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/channels" in str(request.url):
            assert request.headers.get("Authorization") == "Bearer wazzup-key-123"
            return httpx.Response(
                200,
                json=[
                    {
                        "channelId": "ch-wa",
                        "transport": "whatsapp",
                        "plainId": "79001112233",
                        "state": "active",
                    }
                ],
            )
        if "/webhooks" in str(request.url):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    async with _mock_client(handler) as http:
        wz = await WazzupHubAdapter().connect(
            platform_app=None,
            payload={"api_key": "wazzup-key-123"},
            http=http,
        )
        kaspi = await KaspiPayHubAdapter().connect(
            platform_app=None,
            payload={"merchant_id": "m-1", "merchant_token": "kaspi-token-xx"},
            http=http,
        )

    assert wz.api_key == "wazzup-key-123"
    assert (wz.extra or {}).get("metadata", {}).get("channels")[0]["kind"] == "whatsapp"
    assert kaspi.external_account_id == "m-1"


@pytest.mark.asyncio
async def test_whatsapp_hub_connect_refuses_meta_cloud() -> None:
    with pytest.raises(ValueError, match="Wazzup"):
        await WhatsAppHubAdapter().connect(
            platform_app=None,
            payload={"phone_number_id": "999", "access_token": "waba-token-xx"},
            http=MagicMock(),
        )


def test_refresh_connection_is_locked() -> None:
    import inspect

    from app.services.integration_hub.service import IntegrationHubService

    source = inspect.getsource(IntegrationHubService.refresh_connection)
    assert "pg_advisory_xact_lock_hashtext" in source
    assert "pg_advisory_xact_lock_uuid" in source
    assert "with_for_update" in source
    assert "expected_refresh_token" in source


def test_get_hub_adapter_unknown() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        get_hub_adapter("salesforce")


def test_rate_limit_is_per_connection_id(monkeypatch: pytest.MonkeyPatch) -> None:
    counters: dict[str, int] = {}

    class FakeRedis:
        def incr(self, key: str) -> int:
            counters[key] = counters.get(key, 0) + 1
            return counters[key]

        def expire(self, key: str, ttl: int) -> bool:
            return True

        def eval(self, script: str, numkeys: int, *args):
            # Force fixed-window fallback path used in older tests.
            raise RuntimeError("no lua")

    monkeypatch.setattr(
        "app.services.integration_hub.rate_limit.get_redis_client",
        lambda: FakeRedis(),
    )
    a = uuid.uuid4()
    b = uuid.uuid4()
    for _ in range(3):
        acquire_connection_slot(a, limit=3, window_seconds=1)
    with pytest.raises(ConnectionRateLimited):
        acquire_connection_slot(a, limit=3, window_seconds=1)
    acquire_connection_slot(b, limit=3, window_seconds=1)


def test_encrypt_field_envelope_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "k" * 32)
    monkeypatch.setenv("CREDENTIALS_KEY_VERSION", "1")
    monkeypatch.setenv("KMS_KEYS", json.dumps({"1": "k" * 32}))
    sealed = encrypt_field("oauth-client-secret")
    assert "oauth-client-secret" not in sealed
    assert json.loads(sealed)["alg"] == "AESGCM"
    assert decrypt_field(sealed) == "oauth-client-secret"


def test_token_bundle_omits_empty_secrets() -> None:
    payload = TokenBundle(access_token="at", extra={"subdomain": "acme"}).as_vault_payload()
    assert payload["access_token"] == "at"
    assert "refresh_token" not in payload
    assert payload["subdomain"] == "acme"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_skips_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    claims: list[str] = []

    def claim(provider: str, event_id: str, ttl_seconds: int = 30) -> bool:
        claims.append(event_id)
        return True

    channel = SimpleNamespace(
        bot_id=uuid.uuid4(),
        webhook_secret="whsec-test",
        meta_data={},
    )
    monkeypatch.setattr(
        "app.services.webhooks.router_service.claim_inbound_event",
        claim,
    )
    monkeypatch.setattr(
        "app.services.webhooks.router_service.resolve_channel",
        AsyncMock(return_value=channel),
    )
    monkeypatch.setattr(
        "app.services.webhooks.router_service._persist_event_log",
        AsyncMock(return_value=True),
    )

    raw = json.dumps({"channelId": "chan-1", "messageId": "m-1", "text": "hi"}).encode()
    request = MagicMock()
    request.headers.get = lambda name, default=None: (
        "sha256=deadbeef" if name in {"x-signature", "x-hub-signature-256", "x-webhook-signature"} else None
    )
    response = await ingest_provider_webhook(
        provider="wazzup",
        request=request,
        db=AsyncMock(),
        raw_bytes=raw,
    )
    assert isinstance(response, Response)
    assert response.status_code == 403
    assert claims == []


@pytest.mark.asyncio
async def test_webhook_valid_signature_then_dedup_then_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims: list[str] = []
    secret = "whsec-test"
    raw = json.dumps({"channelId": "chan-1", "messageId": "m-1", "text": "hi"}).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    def claim(provider: str, event_id: str, ttl_seconds: int = 30) -> bool:
        claims.append(event_id)
        return True

    channel = SimpleNamespace(
        bot_id=uuid.uuid4(),
        webhook_secret=secret,
        meta_data={},
    )
    monkeypatch.setattr(
        "app.services.webhooks.router_service.claim_inbound_event",
        claim,
    )
    monkeypatch.setattr(
        "app.services.webhooks.router_service.resolve_channel",
        AsyncMock(return_value=channel),
    )
    monkeypatch.setattr(
        "app.services.webhooks.router_service._persist_event_log",
        AsyncMock(return_value=True),
    )
    queued = SimpleNamespace(id="task-42")
    monkeypatch.setattr(
        "app.services.webhooks.router_service.process_inbound_message_task.apply_async",
        lambda *a, **k: queued,
    )

    request = MagicMock()
    request.headers.get = lambda name, default=None: (
        f"sha256={digest}" if name in {"x-signature", "x-hub-signature-256", "x-webhook-signature"} else None
    )
    response = await ingest_provider_webhook(
        provider="wazzup",
        request=request,
        db=AsyncMock(),
        raw_bytes=raw,
    )
    assert claims == ["chan-1:m-1"]
    assert getattr(response, "status") == "queued"
    assert getattr(response, "task_id") == "task-42"


@pytest.mark.asyncio
async def test_webhook_unmatched_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    claims: list[str] = []
    monkeypatch.setattr(
        "app.services.webhooks.router_service.claim_inbound_event",
        lambda *a, **k: claims.append("x") or True,
    )
    monkeypatch.setattr(
        "app.services.webhooks.router_service.resolve_channel",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.webhooks.router_service._persist_event_log",
        AsyncMock(return_value=True),
    )
    raw = json.dumps({"channelId": "missing", "messageId": "m-1", "text": "hi"}).encode()
    request = MagicMock()
    request.headers.get = lambda *a, **k: None
    db = AsyncMock()
    response = await ingest_provider_webhook(
        provider="wazzup",
        request=request,
        db=db,
        raw_bytes=raw,
    )
    assert isinstance(response, Response)
    assert response.status_code == 200
    assert claims == []
