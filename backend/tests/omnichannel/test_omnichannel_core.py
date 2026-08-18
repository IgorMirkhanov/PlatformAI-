"""Step 2.1 — Omnichannel core: schemas, message log, connector registry."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from app.models.omnichannel.message_log import OmnichannelMessageLog
from app.schemas.omnichannel.message import InboundMessage, OutboundMessage
from app.services.omnichannel.base_connector import (
    BaseChannelConnector,
    ChannelRegistry,
    UnknownChannelError,
    get_channel_connector,
)
from app.services.omnichannel.message_log_service import MessageLogService


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self) -> None:
        self.logs: dict[uuid.UUID, OmnichannelMessageLog] = {}


class FakeSession:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, obj: Any) -> None:
        if isinstance(obj, OmnichannelMessageLog):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            self.store.logs[obj.id] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def execute(self, stmt: Any) -> Any:
        rows = self._filter(stmt)

        class _Result:
            def scalars(self_inner) -> Any:
                class _S:
                    def all(self_s) -> list[Any]:
                        return list(rows)

                return _S()

        return _Result()

    def _filter(self, stmt: Any) -> list[OmnichannelMessageLog]:
        try:
            compiled = stmt.compile(compile_kwargs={"render_postcompile": True})
            params = dict(compiled.params or {})
        except Exception:
            params = {}

        values = list(params.values())
        rows = list(self.store.logs.values())
        org_ids = [v for v in values if isinstance(v, uuid.UUID)]
        strings = [v for v in values if isinstance(v, str)]

        if org_ids:
            rows = [r for r in rows if r.organization_id == org_ids[0]]
        for s in strings:
            if s in {"inbound", "outbound"}:
                rows = [r for r in rows if r.direction == s]
            elif s in {"whatsapp", "telegram", "web_chat"}:
                rows = [r for r in rows if r.channel == s]
            else:
                # sender_recipient filter
                matched = [r for r in rows if r.sender_recipient == s]
                if matched:
                    rows = matched
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows


def test_inbound_outbound_schema_mapping() -> None:
    org_id = uuid.uuid4()
    ts = _now()
    inbound = InboundMessage(
        channel="telegram",
        channel_message_id="tg-42",
        organization_id=org_id,
        sender_id="123456",
        sender_name="Aigerim",
        content="Здравствуйте!",
        media_urls=["https://cdn.example/a.jpg"],
        raw_payload={"update_id": 1, "message": {"text": "Здравствуйте!"}},
        timestamp=ts,
    )
    assert inbound.channel == "telegram"
    assert inbound.sender_id == "123456"
    assert inbound.media_urls == ["https://cdn.example/a.jpg"]
    assert inbound.raw_payload["update_id"] == 1

    outbound = OutboundMessage(
        channel="whatsapp",
        recipient_id="+77001234567",
        content="Ваша заявка принята",
        media_urls=None,
        reply_to_message_id="wamid.ABC",
    )
    assert outbound.recipient_id == "+77001234567"
    assert outbound.reply_to_message_id == "wamid.ABC"

    dumped = inbound.model_dump()
    restored = InboundMessage.model_validate(dumped)
    assert restored.organization_id == org_id
    assert restored.content == "Здравствуйте!"

    with pytest.raises(ValidationError):
        OutboundMessage(channel="telegram", recipient_id="", content="x")


@pytest.mark.asyncio
async def test_message_log_tenant_isolation() -> None:
    store = Store()
    db = FakeSession(store)
    service = MessageLogService()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    inbound_a = InboundMessage(
        channel="whatsapp",
        channel_message_id="wa-1",
        organization_id=org_a,
        sender_id="+77001112233",
        content="Hello from A",
        timestamp=_now(),
    )
    inbound_b = InboundMessage(
        channel="whatsapp",
        channel_message_id="wa-2",
        organization_id=org_b,
        sender_id="+77009998877",
        content="Hello from B",
        timestamp=_now(),
    )

    await service.log_inbound(db, inbound_a)  # type: ignore[arg-type]
    await service.log_inbound(db, inbound_b)  # type: ignore[arg-type]
    await service.log_outbound(
        db,  # type: ignore[arg-type]
        org_a,
        OutboundMessage(
            channel="whatsapp",
            recipient_id="+77001112233",
            content="Reply A",
        ),
    )

    listed_a = await service.list_for_organization(db, org_a)  # type: ignore[arg-type]
    assert len(listed_a) == 2
    assert all(r.organization_id == org_a for r in listed_a)
    assert {r.content for r in listed_a} == {"Hello from A", "Reply A"}

    listed_b = await service.list_for_organization(db, org_b)  # type: ignore[arg-type]
    assert len(listed_b) == 1
    assert listed_b[0].content == "Hello from B"
    assert listed_b[0].direction == "inbound"


def test_channel_registry_register_and_create() -> None:
    @ChannelRegistry.register("test_echo")
    class EchoConnector(BaseChannelConnector):
        def __init__(self, *, prefix: str = "") -> None:
            self.prefix = prefix

        async def send_message(self, message: OutboundMessage) -> bool:
            return bool(message.content)

        async def parse_webhook(self, raw_data: dict[str, Any]) -> InboundMessage:
            return InboundMessage(
                channel="test_echo",
                channel_message_id=str(raw_data.get("id", "1")),
                organization_id=uuid.UUID(str(raw_data["organization_id"])),
                sender_id=str(raw_data.get("from", "unknown")),
                content=f"{self.prefix}{raw_data.get('text', '')}",
                timestamp=_now(),
                raw_payload=raw_data,
            )

    try:
        assert "test_echo" in ChannelRegistry.available()
        connector = get_channel_connector("test_echo", prefix=">>")
        assert isinstance(connector, BaseChannelConnector)
        assert connector.channel_id == "test_echo"

        with pytest.raises(UnknownChannelError):
            ChannelRegistry.create("not-a-real-channel")
    finally:
        ChannelRegistry._registry.pop("test_echo", None)


@pytest.mark.asyncio
async def test_connector_parse_and_send_roundtrip() -> None:
    @ChannelRegistry.register("web_chat_stub")
    class WebChatStub(BaseChannelConnector):
        async def send_message(self, message: OutboundMessage) -> bool:
            return message.channel == "web_chat_stub"

        async def parse_webhook(self, raw_data: dict[str, Any]) -> InboundMessage:
            return InboundMessage(
                channel="web_chat_stub",
                channel_message_id=str(raw_data["mid"]),
                organization_id=uuid.UUID(str(raw_data["org"])),
                sender_id=str(raw_data["visitor"]),
                content=str(raw_data["body"]),
                timestamp=_now(),
                raw_payload=raw_data,
            )

    try:
        connector = ChannelRegistry.create("web_chat_stub")
        org = uuid.uuid4()
        inbound = await connector.parse_webhook(
            {"mid": "m-1", "org": str(org), "visitor": "v-9", "body": "Hi"}
        )
        assert inbound.content == "Hi"
        assert inbound.organization_id == org
        ok = await connector.send_message(
            OutboundMessage(channel="web_chat_stub", recipient_id="v-9", content="Hello")
        )
        assert ok is True
    finally:
        ChannelRegistry._registry.pop("web_chat_stub", None)
