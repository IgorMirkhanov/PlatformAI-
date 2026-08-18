"""Step 2.2 — WhatsApp Cloud API connector tests (mocked httpx)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import httpx
import pytest

from app.schemas.omnichannel.message import OutboundMessage
from app.services.omnichannel.base_connector import ChannelRegistry, get_channel_connector
from app.services.omnichannel.connectors.whatsapp_connector import (
    WhatsAppAuthError,
    WhatsAppConnector,
)


def _meta_inbound_payload(*, sender: str = "77001234567", text: str = "Привет") -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": "PHONE_ID",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Aigerim"},
                                    "wa_id": sender,
                                }
                            ],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": "wamid.TEST123",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def test_whatsapp_registered_in_channel_registry() -> None:
    import app.services.omnichannel.connectors  # noqa: F401

    assert "whatsapp" in ChannelRegistry.available()
    connector = get_channel_connector(
        "whatsapp",
        organization_id=uuid.uuid4(),
        access_token="tok",
        phone_number_id="123",
    )
    assert isinstance(connector, WhatsAppConnector)


def test_verify_webhook_accepts_matching_token() -> None:
    connector = WhatsAppConnector(verify_token="secret-verify")
    challenge = connector.verify_webhook(
        hub_mode="subscribe",
        hub_verify_token="secret-verify",
        hub_challenge="12345",
    )
    assert challenge == "12345"


def test_verify_webhook_rejects_bad_token() -> None:
    connector = WhatsAppConnector(verify_token="secret-verify")
    assert (
        connector.verify_webhook(
            hub_mode="subscribe",
            hub_verify_token="wrong",
            hub_challenge="12345",
        )
        is None
    )


@pytest.mark.asyncio
async def test_parse_webhook_maps_meta_json_to_inbound() -> None:
    org_id = uuid.uuid4()
    connector = WhatsAppConnector(organization_id=org_id)
    inbound = await connector.parse_webhook(_meta_inbound_payload())

    assert inbound.channel == "whatsapp"
    assert inbound.channel_message_id == "wamid.TEST123"
    assert inbound.organization_id == org_id
    assert inbound.sender_id == "77001234567"
    assert inbound.sender_name == "Aigerim"
    assert inbound.content == "Привет"
    assert inbound.raw_payload["object"] == "whatsapp_business_account"
    assert isinstance(inbound.timestamp, datetime)
    assert inbound.timestamp.tzinfo is not None


@pytest.mark.asyncio
async def test_send_message_posts_graph_api_with_bearer() -> None:
    org_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read()
        return httpx.Response(200, json={"messages": [{"id": "wamid.OUT1"}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = WhatsAppConnector(
            organization_id=org_id,
            access_token="EAAB-test-token",
            phone_number_id="10987654321",
            api_version="v18.0",
            base_url="https://graph.facebook.com",
            http_client=client,
        )
        ok = await connector.send_message(
            OutboundMessage(
                channel="whatsapp",
                recipient_id="77001234567",
                content="Ваша заявка принята",
            )
        )

    assert ok is True
    assert captured["method"] == "POST"
    assert captured["url"] == "https://graph.facebook.com/v18.0/10987654321/messages"
    assert captured["headers"].get("authorization") == "Bearer EAAB-test-token"
    import json

    body = json.loads(captured["body"].decode("utf-8"))
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == "77001234567"
    assert body["type"] == "text"
    assert body["text"]["body"] == "Ваша заявка принята"


@pytest.mark.asyncio
async def test_send_template_message_payload() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, json={"messages": [{"id": "wamid.TPL"}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = WhatsAppConnector(
            access_token="tok",
            phone_number_id="111",
            http_client=client,
        )
        await connector.send_message(
            OutboundMessage(
                channel="whatsapp",
                recipient_id="77001112233",
                content="",
                template_name="order_confirm",
                template_language="ru",
                template_components=[
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": "42"}],
                    }
                ],
            )
        )

    import json

    body = json.loads(captured["body"].decode("utf-8"))
    assert body["type"] == "template"
    assert body["template"]["name"] == "order_confirm"
    assert body["template"]["language"]["code"] == "ru"


@pytest.mark.asyncio
async def test_send_message_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Invalid OAuth access token", "code": 190}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        connector = WhatsAppConnector(
            access_token="bad",
            phone_number_id="111",
            http_client=client,
        )
        with pytest.raises(WhatsAppAuthError):
            await connector.send_message(
                OutboundMessage(channel="whatsapp", recipient_id="1", content="x")
            )


@pytest.mark.asyncio
async def test_send_message_missing_credentials() -> None:
    connector = WhatsAppConnector(access_token="", phone_number_id="")
    with pytest.raises(WhatsAppAuthError):
        await connector.send_message(
            OutboundMessage(channel="whatsapp", recipient_id="1", content="x")
        )
