"""Step 3.1 — Flow execution engine: Redis sessions + loop protection."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.services.flow.engine import (
    FlowExecutionEngine,
    FlowExecutionLoopError,
    FlowSessionManager,
    FlowSessionState,
)
from app.services.flow.executor import execute_flow


class InMemoryAsyncRedis:
    """Minimal async Redis stand-in for unit tests (get/set/delete + TTL ignored)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


def _linear_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "trigger", "type": "trigger", "data": {}},
            {
                "id": "message",
                "type": "message",
                "data": {"text": "Hello {{name}}!"},
            },
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "message"},
            {"id": "e2", "source": "message", "target": "end"},
        ],
    }


def _loop_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "A", "type": "message", "data": {"text": "Node A"}},
            {"id": "B", "type": "message", "data": {"text": "Node B"}},
        ],
        "edges": [
            {"id": "ab", "source": "A", "target": "B"},
            {"id": "ba", "source": "B", "target": "A"},
        ],
    }


@pytest.mark.asyncio
async def test_linear_flow_persists_session_in_redis() -> None:
    redis = InMemoryAsyncRedis()
    manager = FlowSessionManager(redis_client=redis, ttl_seconds=3600)
    flow_id = str(uuid.uuid4())
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    result = await execute_flow(
        None,
        flow_id,
        session_id,
        {"name": "Aigerim", "message": "hi"},
        graph=_linear_graph(),
        session_manager=manager,
        max_execution_steps=50,
    )

    assert result.status == "completed"
    assert result.is_terminal is True
    assert result.steps_executed == 3
    assert result.path == ["trigger", "message", "end"]
    assert result.variables.get("name") == "Aigerim"
    message_out = next(o for o in result.outputs if o.get("event") == "message")
    assert message_out["text"] == "Hello Aigerim!"

    # Session persisted in Redis with end cursor + variables.
    raw = await redis.get(f"flow:session:{session_id}")
    assert raw is not None
    stored = json.loads(raw)
    assert stored["flow_id"] == flow_id
    assert stored["current_node_id"] == "end"
    assert stored["session_variables"]["name"] == "Aigerim"

    reloaded = await manager.get(session_id)
    assert isinstance(reloaded, FlowSessionState)
    assert reloaded.current_node_id == "end"


@pytest.mark.asyncio
async def test_loop_protection_raises_and_does_not_hang() -> None:
    redis = InMemoryAsyncRedis()
    manager = FlowSessionManager(redis_client=redis)
    engine = FlowExecutionEngine(manager, max_execution_steps=10)
    session = await manager.get_or_create(
        session_id="loop-sess",
        flow_id="loop-flow",
    )

    with pytest.raises(FlowExecutionLoopError) as exc_info:
        await engine.run(
            graph=_loop_graph(),
            session=session,
            initial_input={"message": "ping"},
        )

    err = exc_info.value
    assert err.max_execution_steps == 10
    assert err.steps == 11
    assert err.session_id == "loop-sess"
    assert "infinite loop" in str(err).lower() or "max_execution_steps" in str(err)

    # Session was saved at the point of failure (cursor preserved).
    saved = await manager.get("loop-sess")
    assert saved is not None
    assert saved.current_node_id in {"A", "B"}


@pytest.mark.asyncio
async def test_execute_flow_raise_on_loop_false_returns_safe_result() -> None:
    redis = InMemoryAsyncRedis()
    manager = FlowSessionManager(redis_client=redis)

    result = await execute_flow(
        None,
        "loop-flow",
        "safe-loop",
        {"message": "x"},
        graph=_loop_graph(),
        session_manager=manager,
        max_execution_steps=5,
        raise_on_loop=False,
    )

    assert result.status == "loop_error"
    assert result.error is not None
    assert result.steps_executed == 6
    assert result.is_terminal is True


@pytest.mark.asyncio
async def test_session_manager_get_or_create_merges_variables() -> None:
    redis = InMemoryAsyncRedis()
    manager = FlowSessionManager(redis_client=redis)
    sid = "merge-1"
    first = await manager.get_or_create(
        session_id=sid, flow_id="f1", initial_variables={"a": 1}
    )
    first.session_variables["b"] = 2
    await manager.save(first)

    second = await manager.get_or_create(
        session_id=sid, flow_id="f1", initial_variables={"c": 3}
    )
    assert second.session_variables["a"] == 1
    assert second.session_variables["b"] == 2
    assert second.session_variables["c"] == 3
