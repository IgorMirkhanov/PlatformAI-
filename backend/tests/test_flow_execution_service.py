"""Unit / integration-ish tests for FlowExecutionService (mocked LLM + graph)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.flow_execution_service import flow_execution_service
from app.services.flow_parser import FlowExecutionResult


class _FakeDb:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.committed = False

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self.bot

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    async def commit(self) -> None:
        self.committed = True

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None

    async def scalar(self, _stmt: Any) -> Any:
        return 0

    def add(self, _obj: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_execute_turn_streams_events(monkeypatch):
    bot_id = uuid.uuid4()
    user_id = uuid.uuid4()
    bot = SimpleNamespace(
        id=bot_id,
        user_id=user_id,
        organization_id=user_id,
        deleted_at=None,
    )
    db = _FakeDb(bot)

    async def fake_load(_db, _bot_id, *, use_draft: bool = False):
        return {
            "nodes": [
                {"id": "t1", "type": "trigger", "data": {}},
                {
                    "id": "m1",
                    "type": "text_message",
                    "data": {"text": "Hello {{message}}", "buttons": []},
                },
            ],
            "edges": [{"id": "e1", "source": "t1", "target": "m1"}],
        }

    async def fake_execute(self, **kwargs):
        return FlowExecutionResult(
            node_id="m1",
            node_type="text_message",
            text="Hello world",
            is_waiting=False,
        )

    events: list[dict[str, Any]] = []

    async def on_event(event: dict[str, Any]) -> None:
        events.append(event)

    monkeypatch.setattr(flow_execution_service, "_load_graph", fake_load)
    monkeypatch.setattr(
        "app.services.flow_parser.FlowExecutor.execute",
        fake_execute,
    )

    async def noop_usage(*_a, **_k):
        return SimpleNamespace(id=uuid.uuid4())

    async def noop_quota(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.services.usage_service.usage_service.record_and_debit",
        noop_usage,
    )
    monkeypatch.setattr(
        "app.services.quota_service.quota_service.assert_message_quota",
        noop_quota,
    )

    result = await flow_execution_service.execute_turn(
        db,  # type: ignore[arg-type]
        bot_id=bot_id,
        message="world",
        on_event=on_event,
        use_draft=True,
    )

    assert result.reply_text == "Hello world"
    assert result.session_id
    assert any(e.get("type") == "start" for e in events)
    assert any(e.get("type") == "done" for e in events)


@pytest.mark.asyncio
async def test_execute_missing_bot_raises():
    db = _FakeDb(None)
    with pytest.raises(ValueError, match="Bot not found"):
        await flow_execution_service.execute_turn(
            db,  # type: ignore[arg-type]
            bot_id=uuid.uuid4(),
            message="hi",
        )
