"""Multi-Wazzup: one org, two bots, two channelIds — isolated routing & API keys."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.wazzup_webhook import _handle_wazzup_payload
from app.core.security import encrypt_credential
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.schemas.core_schemas import WebhookQueuedResponse
from app.services.inbound.outbound_router import _deliver_wazzup
from app.services.wazzup_service import WazzupService, wazzup_service


def _channel(
    *,
    bot_id: uuid.UUID,
    reference_id: str,
    api_key: str,
    organization_id: uuid.UUID | None = None,
) -> MagicMock:
    row = MagicMock(spec=BotChannel)
    row.id = uuid.uuid4()
    row.bot_id = bot_id
    row.channel_type = HubChannelType.WAZZUP
    row.status = HubChannelStatus.CONNECTED
    row.encrypted_token = encrypt_credential(api_key)
    row.reference_id = reference_id
    row.meta_data = {}
    row.bot = SimpleNamespace(organization_id=organization_id, id=bot_id)
    return row


def _wazzup_payload(*, channel_id: str, chat_id: str, text: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "channelId": channel_id,
                "chatId": chat_id,
                "text": text,
                "contactName": chat_id,
                "isOutbound": False,
            }
        ]
    }


@pytest.mark.asyncio
async def test_extract_channel_id_from_messages_and_top_level() -> None:
    svc = WazzupService()
    assert svc.extract_channel_id({"channelId": "ch-top"}) == "ch-top"
    assert (
        svc.extract_channel_id({"messages": [{"channelId": "ch-msg", "chatId": "1", "text": "hi"}]})
        == "ch-msg"
    )


@pytest.mark.asyncio
async def test_resolve_api_key_uses_channel_token_not_global(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.wazzup_service.settings.WAZZUP_API_KEY",
        "PLATFORM_GLOBAL_KEY_SHOULD_NOT_WIN",
    )
    channel = _channel(
        bot_id=uuid.uuid4(),
        reference_id="ch-1",
        api_key="tenant-key-alpha",
    )
    assert wazzup_service.resolve_api_key(channel) == "tenant-key-alpha"


@pytest.mark.asyncio
async def test_resolve_api_key_falls_back_to_platform_only_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.wazzup_service.settings.WAZZUP_API_KEY",
        "platform-fallback",
    )
    assert wazzup_service.resolve_api_key(None) == "platform-fallback"


@pytest.mark.asyncio
async def test_parallel_webhooks_route_to_correct_bots_and_tokens() -> None:
    """Org with Bot A / Bot B — each Wazzup channelId keeps its own API key & bot."""
    org_id = uuid.uuid4()
    bot_a_id = uuid.uuid4()
    bot_b_id = uuid.uuid4()
    channel_a = _channel(
        bot_id=bot_a_id,
        reference_id="channel_id_1",
        api_key="api-key-bot-a",
        organization_id=org_id,
    )
    channel_b = _channel(
        bot_id=bot_b_id,
        reference_id="channel_id_2",
        api_key="api-key-bot-b",
        organization_id=org_id,
    )

    send_calls: list[dict[str, Any]] = []
    inbound_calls: list[dict[str, Any]] = []

    async def fake_process_inbound(**kwargs: Any) -> Any:
        inbound_calls.append(kwargs)
        return SimpleNamespace(
            response_text=f"reply-from-{kwargs['bot_id']}",
            bot_silent=False,
        )

    async def fake_send(**kwargs: Any) -> None:
        send_calls.append(kwargs)

    channels_by_id = {channel_a.id: channel_a, channel_b.id: channel_b}
    db = AsyncMock(spec=AsyncSession)
    db.get = AsyncMock(side_effect=lambda _model, pk: channels_by_id.get(pk))

    svc = WazzupService()
    with (
        patch(
            "app.services.wazzup_service.process_inbound_message",
            side_effect=fake_process_inbound,
        ),
        patch.object(svc, "send_text_message", side_effect=fake_send),
    ):
        result_a = await svc.process_queued_webhook(
            db,
            bot_id=bot_a_id,
            webhook_body=_wazzup_payload(
                channel_id="channel_id_1",
                chat_id="+77001110001",
                text="hello A",
            ),
            bot_channel_id=channel_a.id,
        )
        result_b = await svc.process_queued_webhook(
            db,
            bot_id=bot_b_id,
            webhook_body=_wazzup_payload(
                channel_id="channel_id_2",
                chat_id="+77001110002",
                text="hello B",
            ),
            bot_channel_id=channel_b.id,
        )

    assert result_a["status"] == "processed"
    assert result_b["status"] == "processed"
    assert result_a["bot_id"] == str(bot_a_id)
    assert result_b["bot_id"] == str(bot_b_id)

    assert len(inbound_calls) == 2
    assert inbound_calls[0]["bot_id"] == bot_a_id
    assert inbound_calls[1]["bot_id"] == bot_b_id
    assert inbound_calls[0]["external_id"] == "+77001110001"
    assert inbound_calls[1]["external_id"] == "+77001110002"
    assert inbound_calls[0]["message_text"] == "hello A"
    assert inbound_calls[1]["message_text"] == "hello B"

    assert len(send_calls) == 2
    assert send_calls[0]["api_key"] == "api-key-bot-a"
    assert send_calls[0]["channel_id"] == "channel_id_1"
    assert send_calls[1]["api_key"] == "api-key-bot-b"
    assert send_calls[1]["channel_id"] == "channel_id_2"
    assert send_calls[0]["api_key"] != send_calls[1]["api_key"]


@pytest.mark.asyncio
async def test_webhook_router_returns_200_for_unknown_channel_id() -> None:
    db = AsyncMock(spec=AsyncSession)
    request = MagicMock(spec=Request)

    with (
        patch("app.core.webhook_auth.require_internal_service_key", return_value=None),
        patch("app.core.redis_client.claim_inbound_event", return_value=True),
        patch.object(
            wazzup_service,
            "get_channel_by_reference_id",
            new=AsyncMock(return_value=None),
        ),
        patch.object(wazzup_service, "get_channel", new=AsyncMock(return_value=None)),
    ):
        response = await _handle_wazzup_payload(
            request=request,
            db=db,
            raw_body=_wazzup_payload(
                channel_id="unknown_channel",
                chat_id="+7700",
                text="ping",
            ),
            path_bot_id=None,
        )

    assert getattr(response, "status_code", None) == 200


@pytest.mark.asyncio
async def test_webhook_router_enqueues_resolved_bot() -> None:
    org_id = uuid.uuid4()
    bot_id = uuid.uuid4()
    channel = _channel(
        bot_id=bot_id,
        reference_id="channel_id_1",
        api_key="k",
        organization_id=org_id,
    )
    db = AsyncMock(spec=AsyncSession)
    request = MagicMock(spec=Request)
    queued = WebhookQueuedResponse(status="queued", task_id="task-1")

    with (
        patch("app.core.webhook_auth.require_internal_service_key", return_value=None),
        patch("app.core.redis_client.claim_inbound_event", return_value=True),
        patch.object(
            wazzup_service,
            "get_channel_by_reference_id",
            new=AsyncMock(return_value=channel),
        ),
        patch(
            "app.api.endpoints.wazzup_webhook._enqueue_inbound_message",
            return_value=queued,
        ) as enqueue,
    ):
        response = await _handle_wazzup_payload(
            request=request,
            db=db,
            raw_body=_wazzup_payload(
                channel_id="channel_id_1",
                chat_id="+77001112233",
                text="route me",
            ),
            path_bot_id=None,
        )

    assert response == queued
    assert enqueue.call_args.kwargs["bot_id"] == str(bot_id)
    assert enqueue.call_args.kwargs["platform_type"] == "WAZZUP"
    payload = enqueue.call_args.kwargs["payload"]
    assert payload["bot_id"] == str(bot_id)
    assert payload["organization_id"] == str(org_id)
    assert payload["channel_id"] == "channel_id_1"


@pytest.mark.asyncio
async def test_outbound_deliver_uses_matching_channel_token() -> None:
    bot_id = uuid.uuid4()
    channel = _channel(bot_id=bot_id, reference_id="channel_id_1", api_key="outbound-key-a")
    db = AsyncMock(spec=AsyncSession)
    send = AsyncMock()

    with (
        patch.object(wazzup_service, "get_channel", new=AsyncMock(return_value=channel)),
        patch.object(wazzup_service, "send_text_message", new=send),
    ):
        await _deliver_wazzup(
            db,
            bot_id=bot_id,
            chat_id="+7700",
            reply="pong",
            payload={
                "channel_id": "channel_id_1",
                "inbound_payload": {"channel_id": "channel_id_1"},
            },
        )

    send.assert_awaited_once()
    assert send.await_args.kwargs["api_key"] == "outbound-key-a"
    assert send.await_args.kwargs["channel_id"] == "channel_id_1"
