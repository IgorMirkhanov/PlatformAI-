"""Flow Builder execution engine — Redis sessions + loop-protected state machine."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.core.config import settings

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

START_NODE_TYPES = frozenset({"trigger", "start", "entry"})
TERMINAL_NODE_TYPES = frozenset({"end", "exit", "terminate", "stop"})
WAITING_NODE_TYPES = frozenset({"input", "wait", "human_handoff", "question"})


class FlowExecutionLoopError(RuntimeError):
    """Raised when graph transitions exceed ``max_execution_steps`` (infinite loop)."""

    def __init__(
        self,
        message: str = "Flow execution exceeded max_execution_steps (possible infinite loop).",
        *,
        flow_id: str | None = None,
        session_id: str | None = None,
        steps: int | None = None,
        max_execution_steps: int | None = None,
        current_node_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.flow_id = flow_id
        self.session_id = session_id
        self.steps = steps
        self.max_execution_steps = max_execution_steps
        self.current_node_id = current_node_id


class FlowEngineError(RuntimeError):
    """Generic Flow Builder engine failure."""


@dataclass
class FlowSessionState:
    """Persisted per-dialogue graph cursor + variables."""

    session_id: str
    flow_id: str
    current_node_id: str | None = None
    session_variables: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "flow_id": self.flow_id,
            "current_node_id": self.current_node_id,
            "session_variables": self.session_variables,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowSessionState:
        return cls(
            session_id=str(data.get("session_id") or ""),
            flow_id=str(data.get("flow_id") or ""),
            current_node_id=data.get("current_node_id"),
            session_variables=dict(data.get("session_variables") or {}),
            updated_at=str(data.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        )


class FlowSessionManager:
    """
    Redis-backed session store for Flow Builder.

    Key layout: ``flow:session:{session_id}`` → JSON blob.
    """

    def __init__(
        self,
        redis_client: Any | None = None,
        *,
        key_prefix: str = "flow:session:",
        ttl_seconds: int | None = None,
    ) -> None:
        self._redis = redis_client
        self.key_prefix = key_prefix
        self.ttl_seconds = int(
            ttl_seconds
            if ttl_seconds is not None
            else getattr(settings, "FLOW_SESSION_TTL_SECONDS", 86400)
        )

    async def _client(self) -> Any:
        if self._redis is not None:
            return self._redis
        from app.core.redis_client import get_async_redis

        self._redis = await get_async_redis()
        return self._redis

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    async def get(self, session_id: str) -> FlowSessionState | None:
        client = await self._client()
        raw = await client.get(self._key(session_id))
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            logger.warning("FlowSession.corrupt | session_id={sid}", sid=session_id)
            return None
        if not isinstance(data, dict):
            return None
        return FlowSessionState.from_dict(data)

    async def save(self, state: FlowSessionState) -> None:
        state.updated_at = datetime.now(timezone.utc).isoformat()
        client = await self._client()
        payload = json.dumps(state.to_dict(), ensure_ascii=False, default=str)
        await client.set(self._key(state.session_id), payload, ex=self.ttl_seconds)

    async def get_or_create(
        self,
        *,
        session_id: str,
        flow_id: str,
        initial_variables: dict[str, Any] | None = None,
    ) -> FlowSessionState:
        existing = await self.get(session_id)
        if existing is not None:
            if existing.flow_id != flow_id:
                existing.flow_id = flow_id
            if initial_variables:
                existing.session_variables.update(initial_variables)
            return existing
        state = FlowSessionState(
            session_id=session_id,
            flow_id=flow_id,
            current_node_id=None,
            session_variables=dict(initial_variables or {}),
        )
        await self.save(state)
        return state

    async def clear(self, session_id: str) -> None:
        client = await self._client()
        await client.delete(self._key(session_id))


@dataclass
class FlowStepRecord:
    node_id: str
    node_type: str
    output: dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowExecutionResult:
    """Result of one inbound-triggered graph walk."""

    session_id: str
    flow_id: str
    current_node_id: str | None
    variables: dict[str, Any]
    steps_executed: int
    path: list[str] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"  # completed | waiting | loop_error | error
    error: str | None = None
    is_terminal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "flow_id": self.flow_id,
            "current_node_id": self.current_node_id,
            "variables": self.variables,
            "steps_executed": self.steps_executed,
            "path": self.path,
            "outputs": self.outputs,
            "status": self.status,
            "error": self.error,
            "is_terminal": self.is_terminal,
        }


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or node.get("canvas_id") or "")


def _node_type(node: dict[str, Any]) -> str:
    raw = node.get("type") or (node.get("data") or {}).get("type") or "unknown"
    return str(raw).strip().lower()


def _interpolate(text: str, variables: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        value = variables.get(key)
        return "" if value is None else str(value)

    return _VAR_PATTERN.sub(repl, text)


class FlowExecutionEngine:
    """
    Graph state machine with hard ``max_execution_steps`` loop protection.

    Does not hang on A↔B cycles — raises ``FlowExecutionLoopError`` and returns
    a safe ``FlowExecutionResult`` when caught by ``run_safe``.
    """

    def __init__(
        self,
        session_manager: FlowSessionManager,
        *,
        max_execution_steps: int | None = None,
        node_registry: Any | None = None,
    ) -> None:
        self.sessions = session_manager
        self.max_execution_steps = int(
            max_execution_steps
            if max_execution_steps is not None
            else getattr(settings, "FLOW_MAX_EXECUTION_STEPS", 50)
        )
        if node_registry is None:
            from app.services.flow.nodes.base import build_default_node_registry

            node_registry = build_default_node_registry()
        self.node_registry = node_registry

    def build_indexes(
        self, graph: dict[str, Any]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        nodes = {
            _node_id(n): n
            for n in (graph.get("nodes") or [])
            if isinstance(n, dict) and _node_id(n)
        }
        outgoing: dict[str, list[dict[str, Any]]] = {nid: [] for nid in nodes}
        for edge in graph.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source in outgoing and target in nodes:
                outgoing[source].append(edge)
        return nodes, outgoing

    def find_start_node_id(
        self,
        nodes: dict[str, dict[str, Any]],
        outgoing: dict[str, list[dict[str, Any]]],
    ) -> str | None:
        for nid, node in nodes.items():
            if _node_type(node) in START_NODE_TYPES:
                return nid
        # Fallback: node with no inbound edges.
        inbound = {str(e.get("target")) for edges in outgoing.values() for e in edges}
        for nid in nodes:
            if nid not in inbound:
                return nid
        return next(iter(nodes), None)

    def next_node_id(
        self,
        current_id: str,
        outgoing: dict[str, list[dict[str, Any]]],
        variables: dict[str, Any],
    ) -> str | None:
        edges = outgoing.get(current_id) or []
        if not edges:
            return None
        branch = str(variables.get("branch") or "").strip().lower()
        if branch:
            from app.services.flow.nodes.base import resolve_branch_edge

            branched = resolve_branch_edge(edges, branch)
            if branched:
                return branched
        # Conditional edges: data.condition / label match (optional).
        for edge in edges:
            data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
            condition = data.get("condition") or data.get("when")
            if condition is None:
                continue
            expected = str(condition)
            actual = str(variables.get("last_input") or variables.get("branch") or "")
            if expected == actual or expected in actual:
                return str(edge.get("target"))
        # Default: first non-branch-tagged edge, else first edge.
        for edge in edges:
            data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
            if edge.get("sourceHandle") or data.get("branch"):
                continue
            return str(edge.get("target"))
        return str(edges[0].get("target"))

    async def execute_node(
        self,
        node: dict[str, Any],
        *,
        session: FlowSessionState,
        variables: dict[str, Any],
        initial_input: dict[str, Any],
        outgoing_edges: list[dict[str, Any]] | None = None,
        db: Any | None = None,
        organization_id: Any | None = None,
    ) -> dict[str, Any]:
        from app.services.flow.nodes.base import NodeExecutionContext

        ntype = _node_type(node)
        handler = self.node_registry.get(ntype) if self.node_registry else None
        if handler is None:
            # Unknown type — no-op pass-through (keeps graphs resilient).
            return {"node_id": _node_id(node), "node_type": ntype, "event": "noop"}

        ctx = NodeExecutionContext(
            node=node,
            session=session,
            variables=variables,
            initial_input=initial_input,
            outgoing_edges=list(outgoing_edges or []),
            db=db,
            organization_id=organization_id,
        )
        result = await handler.execute(ctx)
        if result.branch is not None:
            variables["branch"] = result.branch
        return result.as_step_output(node_id=_node_id(node), node_type=ntype)

    async def run(
        self,
        *,
        graph: dict[str, Any],
        session: FlowSessionState,
        initial_input: dict[str, Any] | None = None,
        db: Any | None = None,
        organization_id: Any | None = None,
    ) -> FlowExecutionResult:
        """
        Walk the graph from session cursor (or start) until terminal / wait / loop limit.

        Raises ``FlowExecutionLoopError`` when ``execution_depth`` exceeds the cap.
        """
        initial_input = dict(initial_input or {})
        nodes, outgoing = self.build_indexes(graph)
        if not nodes:
            raise FlowEngineError("Flow graph has no nodes.")

        variables = dict(session.session_variables)
        for key, value in initial_input.items():
            if not str(key).startswith("__"):
                variables[key] = value
        if "message" in initial_input:
            variables["last_input"] = initial_input["message"]

        org_id = organization_id
        if org_id is None and variables.get("organization_id"):
            import uuid as _uuid

            try:
                org_id = _uuid.UUID(str(variables["organization_id"]))
            except (TypeError, ValueError):
                org_id = None

        current_id = session.current_node_id
        if not current_id or current_id not in nodes:
            current_id = self.find_start_node_id(nodes, outgoing)
        if not current_id:
            raise FlowEngineError("Unable to resolve start node.")

        path: list[str] = []
        outputs: list[dict[str, Any]] = []
        execution_depth = 0
        is_terminal = False
        status = "completed"

        while current_id is not None:
            execution_depth += 1
            if execution_depth > self.max_execution_steps:
                logger.critical(
                    "FlowExecution.loop_detected | flow_id={flow} session={sid} "
                    "steps={steps} max={max} node={node} path={path}",
                    flow=session.flow_id,
                    sid=session.session_id,
                    steps=execution_depth,
                    max=self.max_execution_steps,
                    node=current_id,
                    path=path[-10:],
                )
                session.current_node_id = current_id
                session.session_variables = variables
                await self.sessions.save(session)
                raise FlowExecutionLoopError(
                    f"Flow execution exceeded max_execution_steps={self.max_execution_steps} "
                    f"(possible infinite loop at node '{current_id}').",
                    flow_id=session.flow_id,
                    session_id=session.session_id,
                    steps=execution_depth,
                    max_execution_steps=self.max_execution_steps,
                    current_node_id=current_id,
                )

            node = nodes[current_id]
            path.append(current_id)
            step_out = await self.execute_node(
                node,
                session=session,
                variables=variables,
                initial_input=initial_input,
                outgoing_edges=outgoing.get(current_id) or [],
                db=db,
                organization_id=org_id,
            )
            outputs.append(step_out)

            if step_out.get("waiting"):
                status = "waiting"
                session.current_node_id = current_id
                break

            if step_out.get("terminal") or _node_type(node) in TERMINAL_NODE_TYPES:
                is_terminal = True
                status = "completed"
                session.current_node_id = current_id
                break

            nxt = step_out.get("next_node_id") or self.next_node_id(
                current_id, outgoing, variables
            )
            if nxt is None:
                is_terminal = True
                status = "completed"
                session.current_node_id = current_id
                break
            current_id = str(nxt)
        else:
            session.current_node_id = current_id

        session.session_variables = variables
        await self.sessions.save(session)

        return FlowExecutionResult(
            session_id=session.session_id,
            flow_id=session.flow_id,
            current_node_id=session.current_node_id,
            variables=variables,
            steps_executed=execution_depth,
            path=path,
            outputs=outputs,
            status=status,
            error=None,
            is_terminal=is_terminal,
        )

    async def run_safe(
        self,
        *,
        graph: dict[str, Any],
        session: FlowSessionState,
        initial_input: dict[str, Any] | None = None,
        db: Any | None = None,
        organization_id: Any | None = None,
    ) -> FlowExecutionResult:
        """Like ``run``, but converts loop errors into a safe result (no hang)."""
        try:
            return await self.run(
                graph=graph,
                session=session,
                initial_input=initial_input,
                db=db,
                organization_id=organization_id,
            )
        except FlowExecutionLoopError as exc:
            return FlowExecutionResult(
                session_id=session.session_id,
                flow_id=session.flow_id,
                current_node_id=exc.current_node_id or session.current_node_id,
                variables=dict(session.session_variables),
                steps_executed=int(exc.steps or 0),
                path=[],
                outputs=[],
                status="loop_error",
                error=str(exc),
                is_terminal=True,
            )
