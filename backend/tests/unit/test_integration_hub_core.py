"""Integration Hub core: encryption, OAuth state, CRMAdapter HTTP mocks."""

from __future__ import annotations

import json
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services.encryption import decrypt, encrypt
from app.services.integration_hub.crm_adapter import AmoCRMAdapter, Bitrix24Adapter, get_crm_adapter
from app.services.integration_hub.oauth import (
    build_authorize_url,
    decode_oauth_state,
    sign_oauth_state,
)
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle


def test_encrypt_decrypt_roundtrip_never_stores_plaintext() -> None:
    sealed = encrypt("super-secret-refresh-token")
    assert "super-secret-refresh-token" not in sealed
    assert decrypt(sealed) == "super-secret-refresh-token"


def test_oauth_state_roundtrip() -> None:
    workspace = uuid.uuid4()
    agent = uuid.uuid4()
    token = sign_oauth_state(
        workspace_id=workspace,
        provider="amocrm",
        agent_id=agent,
        extra={"subdomain": "acme"},
    )
    claims = decode_oauth_state(token)
    assert claims["workspace_id"] == str(workspace)
    assert claims["agent_id"] == str(agent)
    assert claims["provider"] == "amocrm"
    assert claims["extra"]["subdomain"] == "acme"


def test_amocrm_authorize_url_includes_signed_state() -> None:
    workspace = uuid.uuid4()
    state = sign_oauth_state(workspace_id=workspace, provider="amocrm", extra={"subdomain": "acme"})
    app = PlatformOAuthApp(
        provider="amocrm",
        client_id="platform-client",
        client_secret="platform-secret",
        redirect_uri="https://api.example.com/api/v1/integrations/amocrm/callback",
    )
    url = build_authorize_url(
        platform_app=app,
        provider="amocrm",
        state=state,
        extra={"subdomain": "acme"},
    )
    parsed = urlparse(url)
    assert parsed.netloc == "acme.amocrm.ru"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["platform-client"]
    assert qs["state"] == [state]
    assert "platform-secret" not in url


@pytest.mark.asyncio
async def test_amocrm_crm_adapter_create_contact_and_deal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/v4/account"):
            return httpx.Response(200, json={"id": 1, "name": "Acme"})
        if path.endswith("/api/v4/contacts") and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"contacts": [{"id": 77, "name": "Ada"}]}})
        if path.endswith("/api/v4/leads") and request.method == "POST":
            return httpx.Response(200, json={"_embedded": {"leads": [{"id": 88}]}})
        return httpx.Response(404)

    secrets = TokenBundle(
        access_token="at",
        extra={"subdomain": "acme.amocrm.ru"},
        external_account_id="acme.amocrm.ru",
    )
    adapter = AmoCRMAdapter()
    cid = uuid.uuid4()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        assert await adapter.test_connection(secrets=secrets, http=http, connection_id=cid)
        contact = await adapter.create_contact(
            secrets=secrets, http=http, connection_id=cid, name="Ada", phone="+7700"
        )
        deal = await adapter.create_deal(
            secrets=secrets, http=http, connection_id=cid, title="Lead", contact_id=contact.id
        )
    assert contact.id == "77"
    assert deal.id == "88"


@pytest.mark.asyncio
async def test_bitrix_crm_adapter_create_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.bitrix24.acquire_bitrix_portal_slot",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.bitrix24.acquire_bitrix_connection_slot",
        lambda *a, **k: None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("crm.contact.add"):
            body = json.loads(request.content.decode())
            assert "PHONE" in body["fields"]
            return httpx.Response(200, json={"result": 501})
        return httpx.Response(404)

    secrets = TokenBundle(
        webhook_url="https://acme.bitrix24.ru/rest/1/hook/",
        extra={"auth_mode": "webhook"},
    )
    adapter = Bitrix24Adapter()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        contact = await adapter.create_contact(
            secrets=secrets,
            http=http,
            connection_id=uuid.uuid4(),
            name="Ada",
            phone="+7700",
        )
    assert contact.id == "501"


def test_get_crm_adapter_factory() -> None:
    assert get_crm_adapter("amocrm") is not None
    assert get_crm_adapter("bitrix24") is not None
    assert get_crm_adapter("wazzup") is None
