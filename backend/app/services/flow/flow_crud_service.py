"""Organization-scoped Flow CRUD + graph validation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow import Flow

_TRIGGER_TYPES = frozenset({"trigger", "start", "entry"})


class FlowServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class FlowNotFoundError(FlowServiceError):
    def __init__(self, message: str = "Flow not found.") -> None:
        super().__init__(message, status_code=404)


def _node_type(node: dict[str, Any]) -> str:
    raw = node.get("type")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    nested = data.get("type")
    if isinstance(nested, str) and nested.strip():
        return nested.strip().lower()
    return ""


def validate_flow_graph(
    *,
    name: str | None,
    nodes: list[dict[str, Any]] | None,
    edges: list[dict[str, Any]] | None,
    require_trigger: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Validate graph payload.

    Raises ``FlowServiceError`` when name is empty or no trigger node is present.
    """
    cleaned_name = (name or "").strip() if name is not None else None
    if cleaned_name is not None and not cleaned_name:
        raise FlowServiceError("Flow name must not be empty.")

    node_list = list(nodes or [])
    edge_list = list(edges or [])

    if require_trigger:
        if not node_list:
            raise FlowServiceError("Flow graph must include at least one node.")
        has_trigger = any(_node_type(n) in _TRIGGER_TYPES for n in node_list)
        if not has_trigger:
            raise FlowServiceError(
                "Flow graph must include a start trigger node (type=trigger)."
            )

    # Basic structural sanity: every node needs an id.
    for idx, node in enumerate(node_list):
        if not isinstance(node, dict):
            raise FlowServiceError(f"Node at index {idx} must be an object.")
        if not str(node.get("id") or "").strip():
            raise FlowServiceError(f"Node at index {idx} is missing id.")

    for idx, edge in enumerate(edge_list):
        if not isinstance(edge, dict):
            raise FlowServiceError(f"Edge at index {idx} must be an object.")
        if not str(edge.get("source") or "").strip() or not str(edge.get("target") or "").strip():
            raise FlowServiceError(f"Edge at index {idx} requires source and target.")

    return node_list, edge_list


def graph_from_flow(flow: Flow) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snapshot = flow.graph_snapshot if isinstance(flow.graph_snapshot, dict) else {}
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    if isinstance(nodes, list) and isinstance(edges, list):
        return list(nodes), list(edges)

    # Fallback to related rows when snapshot empty.
    node_rows = [
        {
            "id": n.canvas_id or str(n.id),
            "type": n.type,
            "data": n.data or {},
            "position": n.position or {"x": 0, "y": 0},
        }
        for n in (flow.nodes or [])
    ]
    edge_rows = [
        {
            "id": e.canvas_id or str(e.id),
            "source": e.source,
            "target": e.target,
            "type": e.type,
            "data": e.data or {},
        }
        for e in (flow.edges or [])
    ]
    return node_rows, edge_rows


def build_snapshot(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(existing or {})
    snapshot["nodes"] = nodes
    snapshot["edges"] = edges
    return snapshot


class FlowCrudService:
    """Tenant-aware organization flow management."""

    async def list_flows(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        active_only: bool = False,
    ) -> list[Flow]:
        stmt = select(Flow).where(Flow.organization_id == organization_id)
        if active_only:
            stmt = stmt.where(Flow.is_active.is_(True))
        stmt = stmt.order_by(Flow.updated_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_flow(
        self,
        db: AsyncSession,
        flow_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> Flow:
        flow = await db.get(Flow, flow_id)
        if flow is None or flow.organization_id != organization_id:
            raise FlowNotFoundError()
        return flow

    async def create_flow(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        name: str,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        is_active: bool = True,
    ) -> Flow:
        node_list, edge_list = validate_flow_graph(
            name=name,
            nodes=nodes,
            edges=edges,
            require_trigger=True,
        )
        flow = Flow(
            id=uuid.uuid4(),
            organization_id=organization_id,
            bot_id=None,
            name=name.strip(),
            is_active=bool(is_active),
            graph_snapshot=build_snapshot(node_list, edge_list),
        )
        db.add(flow)
        await db.flush()
        await db.refresh(flow)
        return flow

    async def update_flow(
        self,
        db: AsyncSession,
        flow_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        name: str | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        is_active: bool | None = None,
    ) -> Flow:
        flow = await self.get_flow(db, flow_id, organization_id)
        current_nodes, current_edges = graph_from_flow(flow)

        next_name = name if name is not None else flow.name
        next_nodes = nodes if nodes is not None else current_nodes
        next_edges = edges if edges is not None else current_edges

        # When graph fields change (or name), re-validate trigger presence.
        validate_flow_graph(
            name=next_name,
            nodes=next_nodes,
            edges=next_edges,
            require_trigger=True,
        )

        if name is not None:
            flow.name = name.strip()
        if is_active is not None:
            flow.is_active = bool(is_active)
        if nodes is not None or edges is not None:
            existing = flow.graph_snapshot if isinstance(flow.graph_snapshot, dict) else {}
            flow.graph_snapshot = build_snapshot(next_nodes, next_edges, existing=existing)

        await db.flush()
        await db.refresh(flow)
        return flow

    async def delete_flow(
        self,
        db: AsyncSession,
        flow_id: uuid.UUID,
        organization_id: uuid.UUID,
        *,
        hard: bool = False,
    ) -> Flow:
        flow = await self.get_flow(db, flow_id, organization_id)
        if hard:
            await db.delete(flow)
            await db.flush()
            return flow
        flow.is_active = False
        await db.flush()
        await db.refresh(flow)
        return flow


flow_crud_service = FlowCrudService()
