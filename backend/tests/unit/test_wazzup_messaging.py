"""Wazzup MessagingAdapter: API key, channels metadata, webhook, message.received."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.integration_hub.adapters.wazzup import (
    WazzupHubAdapter,
    summarize_wazzup_channels,
    wazzup_webhook_public_url,
)
from app.services.integration_hub.types import TokenBundle


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _secrets() -> TokenBundle:
    return TokenBundle(
        api_key="wazzup-key-123",
        extra={
            "base_url": "https://api.wazzup24.com/v3",
            "channels": [
                {
                    "channel_id": "ch-wa",
                    "transport": "whatsapp",
                    "kind": "whatsapp",
                    "plain_id": "79001112233",
                    "state": "active",
                }
            ],
            "metadata": {
                "channels": [
                    {
                        "channel_id": "ch-wa",
                        "transport": "whatsapp",
                        "kind": "whatsapp",
                        "plain_id": "79001112233",
                        "state": "active",
                    }
                ]
            },
        },
        external_account_id="ch-wa",
    )


@pytest.mark.asyncio
async def test_connect_lists_channels_into_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/channels")
        return httpx.Response(
            200,
            json=[
                {
                    "channelId": "ch-wa",
                    "transport": "whatsapp",
                    "plainId": "7900",
                    "state": "active",
                },
                {
                    "channelId": "ch-tg",
                    "transport": "tgapi",
                    "plainId": "@bot",
                    "state": "active",
                },
                {
                    "channelId": "ch-ig",
                    "transport": "instagram",
                    "plainId": "shop",
                    "state": "qr",
                },
            ],
        )

    async with _mock_client(handler) as http:
        bundle = await WazzupHubAdapter().connect(
            platform_app=None,
            payload={"api_key": "wazzup-key-123"},
            http=http,
        )
    kinds = {row["kind"] for row in bundle.extra["channels"]}
    assert kinds == {"whatsapp", "telegram", "instagram"}
    assert bundle.extra["metadata"]["channels"][0]["channel_id"] == "ch-wa"
    assert "api_key" not in (bundle.extra or {})


@pytest.mark.asyncio
async def test_bind_registers_webhook_on_connection_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.integration_hub.adapters.wazzup.resolve_webhook_base_url",
        lambda: "https://api.mp.ai",
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={})

    cid = uuid.uuid4()
    async with _mock_client(handler) as http:
        uri = await WazzupHubAdapter().bind_event_handlers(
            secrets=_secrets(), http=http, connection_id=cid
        )
    assert captured["method"] == "PATCH"
    assert str(captured["url"]).endswith("/webhooks")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["webhooksUri"] == f"https://api.mp.ai/webhooks/wazzup/{cid}"
    assert body["subscriptions"]["messagesAndStatuses"] is True
    assert uri == body["webhooksUri"]
    assert len(uri) < 200


def test_parse_incoming_webhook_message_received() -> None:
    events = WazzupHubAdapter().parse_incoming_webhook(
        {
            "messages": [
                {
                    "messageId": "m-1",
                    "channelId": "ch-wa",
                    "chatType": "whatsapp",
                    "chatId": "79001112233",
                    "dateTime": "2026-08-25T10:00:00.000",
                    "text": "hello",
                    "isEcho": False,
                    "contact": {"name": "Ada", "phone": "79001112233"},
                },
                {
                    "messageId": "m-echo",
                    "channelId": "ch-wa",
                    "chatType": "whatsapp",
                    "chatId": "79001112233",
                    "text": "outbound",
                    "isEcho": True,
                },
            ]
        },
        connection_id=uuid.uuid4(),
    )
    assert len(events) == 1
    event = events[0]
    assert event.type == "message.received"
    assert event.channel_type == "whatsapp"
    assert event.text == "hello"
    assert event.from_name == "Ada"
    payload = event.as_dict()
    assert payload["from"]["id"] == "79001112233"


def test_parse_test_ping_is_empty() -> None:
    assert WazzupHubAdapter().parse_incoming_webhook({"test": True}) == []


@pytest.mark.asyncio
async def test_send_message_uses_client_access_token() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"messageId": "out-1"})

    async with _mock_client(handler) as http:
        result = await WazzupHubAdapter().send_message(
            secrets=_secrets(),
            http=http,
            connection_id=uuid.uuid4(),
            chat_id="79001112233",
            text="hi",
        )
    assert captured["auth"] == "Bearer wazzup-key-123"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["channelId"] == "ch-wa"
    assert body["chatType"] == "whatsapp"
    assert body["chatId"] == "79001112233"
    assert result["messageId"] == "out-1"


def test_summarize_and_public_url() -> None:
    rows = summarize_wazzup_channels(
        [{"channelId": "x", "transport": "wapi", "state": "active", "plainId": "1"}]
    )
    assert rows[0]["kind"] == "whatsapp"
    cid = uuid.uuid4()
    url = wazzup_webhook_public_url(cid)
    assert url.endswith(f"/webhooks/wazzup/{cid}")


@pytest.mark.asyncio
async def test_hub_webhook_test_ping_and_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.integration_hub.wazzup_webhook import ingest_wazzup_hub_webhook

    cid = uuid.uuid4()
    conn = SimpleNamespace(
        id=cid,
        provider="wazzup",
        organization_id=uuid.uuid4(),
        bot_id=uuid.uuid4(),
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)
    queued: list[object] = []
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.enqueue_hub_webhook_job",
        lambda event_id: queued.append(event_id),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.claim_webhook_dedup_key",
        lambda *a, **k: True,
    )

    ping = await ingest_wazzup_hub_webhook(connection_id=cid, payload={"test": True}, db=db)
    assert ping.status_code == 200
    assert queued == []

    db.scalar = AsyncMock(return_value=uuid.uuid4())
    resp = await ingest_wazzup_hub_webhook(
        connection_id=cid,
        payload={
            "messages": [
                {
                    "messageId": "m-1",
                    "channelId": "ch-wa",
                    "chatType": "whatsapp",
                    "chatId": "79001112233",
                    "text": "hello",
                    "isEcho": False,
                }
            ]
        },
        db=db,
    )
    assert resp.status_code == 200
    assert len(queued) == 1
    assert queued[0] is not None
