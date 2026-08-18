"""Canonical BotGraph schema — nodes + edges for React Flow / FlowExecutor.

Persisted today as ``BotFlow.graph_data`` JSONB. Normalized ``Flow``/``Node``/``Edge``
tables remain available for future dual-write.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


BackendNodeType = Literal[
    "trigger",
    "text_message",
    "condition",
    "ai_agent",
    "knowledge_search",
    "crm_action",
    "api_request",
]


class BotGraphNode(BaseModel):
    id: str
    type: BackendNodeType
    position: dict[str, float] | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class BotGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: str | None = None

    model_config = {"populate_by_name": True}


class BotGraph(BaseModel):
    """Executable conversation graph."""

    nodes: list[BotGraphNode] = Field(default_factory=list)
    edges: list[BotGraphEdge] = Field(default_factory=list)

    def node_map(self) -> dict[str, BotGraphNode]:
        return {n.id: n for n in self.nodes}

    def outgoing(self, node_id: str) -> list[BotGraphEdge]:
        return [e for e in self.edges if e.source == node_id]

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> "BotGraph":
        if not raw:
            return cls()
        return cls.model_validate(raw)


# Example used in docs / tests
EXAMPLE_RAG_CRM_FLOW: dict[str, Any] = {
    "nodes": [
        {
            "id": "t1",
            "type": "trigger",
            "position": {"x": 0, "y": 0},
            "data": {"trigger_type": "message_received"},
        },
        {
            "id": "rag1",
            "type": "knowledge_search",
            "position": {"x": 280, "y": 0},
            "data": {
                "top_k": 3,
                "query_variable": "message",
                "output_variable": "rag_context",
            },
        },
        {
            "id": "llm1",
            "type": "ai_agent",
            "position": {"x": 560, "y": 0},
            "data": {
                "prompt_context": "Answer using {{rag_context}}. Be concise.",
                "knowledge_base_id": "default",
                "temperature": 0.4,
            },
        },
        {
            "id": "cond1",
            "type": "condition",
            "position": {"x": 840, "y": 0},
            "data": {
                "condition_type": "expression",
                "expression": "{{wants_human}} == true",
                "true_label": "Handoff",
                "false_label": "CRM",
            },
        },
        {
            "id": "msg1",
            "type": "text_message",
            "position": {"x": 1120, "y": -80},
            "data": {"text": "Connecting you to an operator…", "buttons": []},
        },
        {
            "id": "crm1",
            "type": "crm_action",
            "position": {"x": 1120, "y": 80},
            "data": {
                "integration_type": "amocrm",
                "method": "POST",
                "url": "https://example.amocrm.ru/api/v4/leads",
                "body_template": '{"name":"{{user_name}}","phone":"{{phone}}"}',
                "response_variable": "crm_result",
            },
        },
    ],
    "edges": [
        {"id": "e1", "source": "t1", "target": "rag1"},
        {"id": "e2", "source": "rag1", "target": "llm1"},
        {"id": "e3", "source": "llm1", "target": "cond1"},
        {"id": "e4", "source": "cond1", "target": "msg1", "sourceHandle": "true"},
        {"id": "e5", "source": "cond1", "target": "crm1", "sourceHandle": "false"},
    ],
}
