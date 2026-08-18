"""Pydantic v2 schemas for the visual bot-builder (React Flow compatible)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.graph_validation import GraphValidationError, GraphValidationIssue

FlowNodeType = Literal[
    "text_message",
    "condition",
    "ai_agent",
    "knowledge_search",
    "crm_action",
    "api_request",
    "trigger",
    "loop",
    "human_handoff",
    "default",
    "input",
    "output",
]

FlowEdgeType = Literal["default", "smoothstep", "step", "straight", "bezier"]


class PositionSchema(BaseModel):
    """Canvas coordinates for a React Flow node."""

    model_config = ConfigDict(extra="ignore")

    x: float = 0.0
    y: float = 0.0


class NodeSchema(BaseModel):
    """Strict React Flow node payload."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(..., min_length=1, max_length=128)
    type: str = Field(default="text_message", min_length=1, max_length=64)
    position: PositionSchema = Field(default_factory=PositionSchema)
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "type", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("position", mode="before")
    @classmethod
    def _coerce_position(cls, value: Any) -> Any:
        if value is None:
            return {"x": 0.0, "y": 0.0}
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return {"x": float(value[0]), "y": float(value[1])}
        return value

    @field_validator("data", mode="before")
    @classmethod
    def _coerce_data(cls, value: Any) -> Any:
        return value if isinstance(value, dict) else {}


class EdgeSchema(BaseModel):
    """Strict React Flow edge payload."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(..., min_length=1, max_length=128)
    source: str = Field(..., min_length=1, max_length=128)
    target: str = Field(..., min_length=1, max_length=128)
    type: str = Field(default="default", min_length=1, max_length=64)
    source_handle: str | None = Field(default=None, alias="sourceHandle", max_length=128)
    target_handle: str | None = Field(default=None, alias="targetHandle", max_length=128)
    data: dict[str, Any] = Field(default_factory=dict)
    label: str | None = Field(default=None, max_length=255)

    @field_validator("id", "source", "target", "type", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class CompiledFlowGraph(BaseModel):
    """Full canvas document used for save / publish / fetch round-trips."""

    model_config = ConfigDict(extra="ignore")

    nodes: list[NodeSchema] = Field(default_factory=list)
    edges: list[EdgeSchema] = Field(default_factory=list)
    viewport: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> Self:
        issues: list[GraphValidationIssue] = []
        node_ids = {node.id for node in self.nodes}

        duplicate_nodes = _duplicates([node.id for node in self.nodes])
        for node_id in duplicate_nodes:
            issues.append(
                GraphValidationIssue(
                    code="duplicate_node_id",
                    message=f"Duplicate node id '{node_id}'.",
                    node_id=node_id,
                    field="nodes",
                )
            )

        duplicate_edges = _duplicates([edge.id for edge in self.edges])
        for edge_id in duplicate_edges:
            issues.append(
                GraphValidationIssue(
                    code="duplicate_edge_id",
                    message=f"Duplicate edge id '{edge_id}'.",
                    edge_id=edge_id,
                    field="edges",
                )
            )

        for edge in self.edges:
            if edge.source not in node_ids:
                issues.append(
                    GraphValidationIssue(
                        code="edge_unknown_source",
                        message=(
                            f"Edge '{edge.id}' connects from unknown node '{edge.source}'."
                        ),
                        edge_id=edge.id,
                        node_id=edge.source,
                        field="edges",
                    )
                )
            if edge.target not in node_ids:
                issues.append(
                    GraphValidationIssue(
                        code="edge_unknown_target",
                        message=(
                            f"Edge '{edge.id}' points to unknown node '{edge.target}'."
                        ),
                        edge_id=edge.id,
                        node_id=edge.target,
                        field="edges",
                    )
                )
            if edge.source == edge.target:
                issues.append(
                    GraphValidationIssue(
                        code="edge_self_loop",
                        message=f"Edge '{edge.id}' cannot connect a node to itself.",
                        edge_id=edge.id,
                        node_id=edge.source,
                        field="edges",
                    )
                )

        if issues:
            raise GraphValidationError(issues)
        return self


class FlowCreate(BaseModel):
    """Create a new visual flow for a bot."""

    model_config = ConfigDict(extra="ignore")

    bot_id: uuid.UUID
    name: str = Field(default="Untitled Flow", min_length=1, max_length=255)
    is_active: bool = True
    graph: CompiledFlowGraph = Field(default_factory=CompiledFlowGraph)


class FlowUpdate(BaseModel):
    """Partial update for flow metadata and/or graph document."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    graph: CompiledFlowGraph | None = None
    # When true, increments published_version and marks snapshot as published.
    publish: bool = False


class FlowSaveGraphRequest(BaseModel):
    """Dedicated save endpoint body for replacing the full compiled graph."""

    model_config = ConfigDict(extra="ignore")

    graph: CompiledFlowGraph
    name: str | None = Field(default=None, min_length=1, max_length=255)
    publish: bool = False


class FlowPublishRequest(BaseModel):
    """Publish the current (or provided) compiled graph as a new version."""

    model_config = ConfigDict(extra="ignore")

    graph: CompiledFlowGraph | None = None
    note: str | None = Field(default=None, max_length=512)


class NodeRead(NodeSchema):
    """Persisted node row projected back to the canvas."""

    db_id: uuid.UUID | None = None


class EdgeRead(EdgeSchema):
    """Persisted edge row projected back to the canvas."""

    db_id: uuid.UUID | None = None


class FlowRead(BaseModel):
    """Flow metadata + compiled graph for the builder UI."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    name: str
    published_version: int
    is_active: bool
    graph: CompiledFlowGraph
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowSummary(BaseModel):
    """Lightweight list item without the full node/edge payload."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    name: str
    published_version: int
    is_active: bool
    node_count: int = 0
    edge_count: int = 0
    updated_at: datetime | None = None


class FlowListResponse(BaseModel):
    bot_id: uuid.UUID
    flows: list[FlowSummary]
    total: int


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        if value in seen:
            dupes.add(value)
        else:
            seen.add(value)
    return sorted(dupes)


def graph_from_orm_collections(
    *,
    nodes: list[Any],
    edges: list[Any],
    snapshot: dict[str, Any] | None = None,
) -> CompiledFlowGraph:
    """Build a ``CompiledFlowGraph`` from ORM Node/Edge rows or a JSON snapshot."""
    if snapshot and (snapshot.get("nodes") or snapshot.get("edges")):
        return CompiledFlowGraph.model_validate(snapshot)

    node_payload = [
        {
            "id": getattr(node, "canvas_id", None) or str(getattr(node, "id")),
            "type": getattr(node, "type", "default"),
            "position": getattr(node, "position", None) or {"x": 0, "y": 0},
            "data": getattr(node, "data", None) or {},
        }
        for node in nodes
    ]
    edge_payload = []
    for edge in edges:
        data = dict(getattr(edge, "data", None) or {})
        edge_payload.append(
            {
                "id": getattr(edge, "canvas_id", None) or str(getattr(edge, "id")),
                "source": getattr(edge, "source"),
                "target": getattr(edge, "target"),
                "type": getattr(edge, "type", "default"),
                "sourceHandle": data.get("sourceHandle") or data.get("source_handle"),
                "targetHandle": data.get("targetHandle") or data.get("target_handle"),
                "label": data.get("label"),
                "data": data,
            }
        )
    return CompiledFlowGraph.model_validate({"nodes": node_payload, "edges": edge_payload})
