"""Step 2.3 — Telegram Bot API connector tests (mocked httpx)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import httpx
import pytest

from app.schemas.omnichannel.message import OutboundMessage
from app.services.omnichannel.base_connector import ChannelRegistry, get_channel_connector
from app.services.omnichannel.connectors.telegram_connector import (
    TelegramAuthError,
    TelegramConnector,
    TelegramForbiddenError,
)


def _telegram_update(*, chat_id: int = 424242, text: str = "Здравствуйте") -> dict[str, Any]:
    return {
        "update_id": 1001,
        "message": {
            "message_id": 77,
            "date": 1700000000,
            "chat": {"id": chat_id, "type": "private"},
            "from": {
                "id": chat_id,
                "is_bot": False,
                "first_name": "Aigerim",
                "username": "aigerim",
            },
            "text": text,
        },
    }


def test_telegram_registered_in_channel_registry() -> None:
    import app.services.omnichannel.connectors  # noqa: F401

    assert "telegram" in ChannelRegistry.available()
    connector = get_channel_connector(
        "telegram",
        organization_id=uuid.uuid4(),
        bot_token="123:ABC",
    )
    assert isinstance(connector, TelegramConnector)


@pytest.mark.asyncio
async def test_parse_webhook_maps_telegram_update_to_inbound() -> None:
    org_id = uuid.uuid4()
    connector = TelegramConnector(organization_id=org_id, bot_token="")
    inbound = await connector.parse_webhook(_telegram_update())

    assert inbound.channel == "telegram"
    assert inbound.channel_message_id == "77"
    assert inbound.organization_id == org_id
    assert inbound.sender_id == "424242"
    assert inbound.sender_name == "Aigerim"
    assert inbound.content == "Здравствуйте"
    assert inbound.raw_payload["update_id"] == 1001
    assert isinstance(inbound.timestamp, datetime)
    assert inbound.timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_parse_callback_query() -> None:
    org_id = uuid.uuid4()
    connector = TelegramConnector(organization_id=org_id, bot_token="")
    inbound = await connector.parse_webhook(
        {
            "update_id": 2,
            "callback_query": {
                "id": "cq-1",
                "from": {"id": 99, "first_name": "User"},
                "data": "confirm:yes",
                "message": {
                    "message_id": 1,
                    "date": 1700000001,
                    "chat": {"id": 99, "type": "private"},
                },
            },
        }
    )
    assert inbound.content == "confirm:yes"
    assert inbound.sender_id == "99"
    assert inbound.channel_message_id == "cq-1"


@pytest.mark.asyncio
async def test_send_message_posts_send_message_with_token_in_url() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = TelegramConnector(
            organization_id=uuid.uuid4(),
            bot_token="123456:AA-test-token",
            api_base_url="https://api.telegram.org",
            http_client=client,
        )
        ok = await connector.send_message(
            OutboundMessage(
                channel="telegram",
                recipient_id="424242",
                content="Ваша заявка принята",
                parse_mode="HTML",
            )
        )

    assert ok is True
    assert captured["method"] == "POST"
    assert (
        captured["url"]
        == "https://api.telegram.org/bot123456:AA-test-token/sendMessage"
    )
    body = json.loads(captured["body"].decode("utf-8"))
    assert body["chat_id"] == "424242"
    assert body["text"] == "Ваша заявка принята"
    assert body["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_photo_uses_send_photo() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, json={"ok": True, "result": {}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = TelegramConnector(
            bot_token="1:tok",
            http_client=client,
        )
        await connector.send_message(
            OutboundMessage(
                channel="telegram",
                recipient_id="1",
                content="caption",
                media_urls=["https://cdn.example/a.jpg"],
            )
        )

    assert captured["url"].endswith("/sendPhoto")
    body = json.loads(captured["body"].decode("utf-8"))
    assert body["photo"] == "https://cdn.example/a.jpg"
    assert body["caption"] == "caption"


@pytest.mark.asyncio
async def test_send_message_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"ok": False, "error_code": 401, "description": "Unauthorized"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = TelegramConnector(bot_token="bad", http_client=client)
        with pytest.raises(TelegramAuthError):
            await connector.send_message(
                OutboundMessage(channel="telegram", recipient_id="1", content="x")
            )


@pytest.mark.asyncio
async def test_send_message_forbidden_when_bot_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "ok": False,
                "error_code": 403,
                "description": "Forbidden: bot was blocked by the user",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = TelegramConnector(bot_token="tok", http_client=client)
        with pytest.raises(TelegramForbiddenError):
            await connector.send_message(
                OutboundMessage(channel="telegram", recipient_id="1", content="x")
            )


@pytest.mark.asyncio
async def test_send_message_missing_token() -> None:
    connector = TelegramConnector(bot_token="")
    with pytest.raises(TelegramAuthError):
        await connector.send_message(
            OutboundMessage(channel="telegram", recipient_id="1", content="x")
        )
