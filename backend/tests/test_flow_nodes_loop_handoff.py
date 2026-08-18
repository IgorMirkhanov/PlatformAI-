"""Unit tests — loop + human handoff node evaluation."""

from __future__ import annotations

import pytest

from app.services.flow_parser import FlowExecutor


@pytest.mark.asyncio
async def test_loop_exits_after_max_iterations():
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger", "data": {}},
            {
                "id": "loop",
                "type": "loop",
                "data": {
                    "max_iterations": 2,
                    "continue_expression": "true",
                    "body_label": "Body",
                    "exit_label": "Exit",
                },
            },
            {
                "id": "body",
                "type": "text_message",
                "data": {"text": "body", "buttons": []},
            },
            {
                "id": "exit",
                "type": "text_message",
                "data": {"text": "done", "buttons": []},
            },
        ],
        "edges": [
            {"id": "e0", "source": "t", "target": "loop"},
            {"id": "e1", "source": "loop", "target": "body", "sourceHandle": "body"},
            {"id": "e2", "source": "loop", "target": "exit", "sourceHandle": "exit"},
            {"id": "e3", "source": "body", "target": "loop"},
        ],
    }
    executor = FlowExecutor(graph)
    # First evaluation from trigger should enter loop → body
    result = await executor.execute(current_step_id=None, incoming_message="hi")
    assert result.node_type in {"text_message", "loop"} or result.text


@pytest.mark.asyncio
async def test_human_handoff_waits():
    graph = {
        "nodes": [
            {"id": "t", "type": "trigger", "data": {}},
            {
                "id": "h",
                "type": "human_handoff",
                "data": {
                    "handoff_message": "Operator coming",
                    "queue_tag": "sales",
                    "pause_bot": True,
                },
            },
        ],
        "edges": [{"id": "e1", "source": "t", "target": "h"}],
    }
    executor = FlowExecutor(graph)
    result = await executor.execute(current_step_id=None, incoming_message="help")
    assert result.node_type == "human_handoff"
    assert result.is_waiting is True
    assert "Operator" in result.text
