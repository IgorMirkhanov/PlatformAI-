"""Node handler contract + registry for Flow Builder."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flow.engine import FlowSessionState, _interpolate, _node_id, _node_type


@dataclass
class NodeExecutionContext:
    """Runtime context passed to every node handler."""

    node: dict[str, Any]
    session: FlowSessionState
    variables: dict[str, Any]
    initial_input: dict[str, Any]
    outgoing_edges: list[dict[str, Any]] = field(default_factory=list)
    db: AsyncSession | None = None
    organization_id: uuid.UUID | None = None

    @property
    def node_id(self) -> str:
        return _node_id(self.node)

    @property
    def node_type(self) -> str:
        return _node_type(self.node)

    @property
    def data(self) -> dict[str, Any]:
        raw = self.node.get("data")
        return raw if isinstance(raw, dict) else {}

    def interpolate(self, text: str) -> str:
        return _interpolate(text or "", self.variables)


@dataclass
class NodeHandlerResult:
    """Outcome of a single node execution."""

    event: str
    output: dict[str, Any] = field(default_factory=dict)
    next_node_id: str | None = None
    branch: str | None = None
    waiting: bool = False
    terminal: bool = False

    def as_step_output(self, *, node_id: str, node_type: str) -> dict[str, Any]:
        payload = {
            "node_id": node_id,
            "node_type": node_type,
            "event": self.event,
            **self.output,
        }
        if self.waiting:
            payload["waiting"] = True
        if self.terminal:
            payload["terminal"] = True
        if self.branch is not None:
            payload["branch"] = self.branch
        if self.next_node_id is not None:
            payload["next_node_id"] = self.next_node_id
        return payload


class BaseNodeHandler(ABC):
    """Adapter contract for one Flow node type."""

    node_types: tuple[str, ...] = ()

    @abstractmethod
    async def execute(self, ctx: NodeExecutionContext) -> NodeHandlerResult:
        """Run the node and optionally mutate ``ctx.variables``."""


class NodeHandlerRegistry:
    """String node-type → handler instance."""

    def __init__(self) -> None:
        self._handlers: dict[str, BaseNodeHandler] = {}

    def register(self, handler: BaseNodeHandler, *extra_types: str) -> None:
        types = list(handler.node_types) + list(extra_types)
        if not types:
            raise ValueError("Handler must declare at least one node type.")
        for raw in types:
            key = str(raw).strip().lower()
            if key:
                self._handlers[key] = handler

    def get(self, node_type: str) -> BaseNodeHandler | None:
        return self._handlers.get(str(node_type).strip().lower())

    def available(self) -> list[str]:
        return sorted(self._handlers.keys())


def resolve_branch_edge(
    edges: list[dict[str, Any]],
    branch: str,
) -> str | None:
    """Pick outgoing edge for condition branch (true/false)."""
    wanted = str(branch).strip().lower()
    for edge in edges:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        handle = str(edge.get("sourceHandle") or data.get("branch") or data.get("when") or "")
        if handle.strip().lower() == wanted:
            return str(edge.get("target") or "") or None
    return None


def build_default_node_registry(
    *,
    llm_handler: BaseNodeHandler | None = None,
    api_handler: BaseNodeHandler | None = None,
    crm_handler: BaseNodeHandler | None = None,
    sheets_handler: BaseNodeHandler | None = None,
    sql_handler: BaseNodeHandler | None = None,
    image_handler: BaseNodeHandler | None = None,
) -> NodeHandlerRegistry:
    """Wire built-in handlers (optional overrides for tests)."""
    from app.services.flow.nodes.api_request import ApiRequestNodeHandler
    from app.services.flow.nodes.builtins import (
        EndNodeHandler,
        MessageNodeHandler,
        WaitingNodeHandler,
    )
    from app.services.flow.nodes.condition import ConditionNodeHandler
    from app.services.flow.nodes.crm_action import CrmActionNodeHandler
    from app.services.flow.nodes.google_sheets_node import GoogleSheetsNodeHandler
    from app.services.flow.nodes.image_generation_node import ImageGenerationNodeHandler
    from app.services.flow.nodes.llm_node import LLMNodeHandler
    from app.services.flow.nodes.sql_query_node import SqlQueryNodeHandler
    from app.services.flow.nodes.trigger import TriggerNodeHandler

    registry = NodeHandlerRegistry()
    registry.register(TriggerNodeHandler())
    registry.register(ConditionNodeHandler())
    registry.register(llm_handler or LLMNodeHandler())
    registry.register(api_handler or ApiRequestNodeHandler())
    registry.register(crm_handler or CrmActionNodeHandler())
    registry.register(sheets_handler or GoogleSheetsNodeHandler())
    registry.register(sql_handler or SqlQueryNodeHandler())
    registry.register(image_handler or ImageGenerationNodeHandler())
    registry.register(MessageNodeHandler())
    registry.register(EndNodeHandler())
    registry.register(WaitingNodeHandler())
    return registry
