"""Choose prompt replies over the auto-generated starter scenario.

A freshly created agent publishes one static welcome card. That card is not a
scenario the operator built, so inbound messages answer from the system prompt,
model, temperature, and knowledge base. A graph with edges, several nodes, or
buttons is left alone.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.flow_cache import published_flow_cache
from app.models.core_models import BotFlow
from app.schemas.core_schemas import FlowGraphData

PROMPT_AGENT_NODE_ID = "prompt_agent"
_PLAIN_TEXT_TYPES = frozenset({"text_message", "message", "text", "reply", "say"})


def uses_custom_scenario(graph_data: dict[str, Any] | None) -> bool:
    """True when the published graph should run instead of the prompt agent."""
    if not isinstance(graph_data, dict):
        return False
    nodes = graph_data.get("nodes")
    edges = graph_data.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        return False
    if edges:
        return True
    if len(nodes) != 1 or not isinstance(nodes[0], dict):
        return True
    node = nodes[0]
    node_type = str(node.get("type") or "").strip().lower()
    if node_type in {"ai_agent", "llm"}:
        return True
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if data.get("buttons"):
        return True
    if node_type in _PLAIN_TEXT_TYPES:
        return False
    return True


def prompt_reply_graph(bot_id: uuid.UUID) -> dict[str, Any]:
    """Single AI node. Model and temperature stay on the agent record."""
    raw = {
        "nodes": [
            {
                "id": PROMPT_AGENT_NODE_ID,
                "type": "ai_agent",
                "position": {"x": 80.0, "y": 80.0},
                "data": {
                    "prompt_context": "Следуй системным инструкциям агента.",
                    "knowledge_base_id": str(bot_id),
                },
            }
        ],
        "edges": [],
    }
    dumped = FlowGraphData.model_validate(raw).model_dump(mode="json")
    for node in dumped.get("nodes") or []:
        data = node.get("data") if isinstance(node, dict) else None
        if isinstance(data, dict):
            data.pop("temperature", None)
    return dumped


async def adopt_prompt_reply_graph(db: AsyncSession, bot_id: uuid.UUID) -> dict[str, Any]:
    """Replace a starter card with the prompt agent and return that graph."""
    graph = prompt_reply_graph(bot_id)
    result = await db.execute(
        select(BotFlow)
        .where(BotFlow.bot_id == bot_id, BotFlow.is_published.is_(True))
        .order_by(BotFlow.updated_at.desc())
        .limit(1)
    )
    flow = result.scalar_one_or_none()
    if flow is None:
        flow = BotFlow(
            bot_id=bot_id,
            title="Ответы по промпту",
            graph_data=graph,
            is_published=True,
        )
        db.add(flow)
    else:
        flow.graph_data = graph
        flow.is_published = True
        flag_modified(flow, "graph_data")
    await db.flush()
    published_flow_cache.invalidate(bot_id)
    published_flow_cache.put_from_orm(
        flow_id=flow.id,
        bot_id=bot_id,
        title=flow.title,
        graph_data=graph,
        is_published=True,
        updated_at=flow.updated_at,
    )
    return graph
