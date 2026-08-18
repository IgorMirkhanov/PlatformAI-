"""Flow Builder public executor — load graph, resume Redis session, run engine."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flow.engine import (
    FlowEngineError,
    FlowExecutionEngine,
    FlowExecutionLoopError,
    FlowExecutionResult,
    FlowSessionManager,
)


async def load_flow_graph(db: AsyncSession | None, flow_id: str) -> dict[str, Any]:
    """
    Load a React Flow-compatible graph for ``flow_id``.

    Prefers ``Flow.graph_snapshot``; falls back to related Node/Edge rows.
    """
    if db is None:
        raise FlowEngineError("Database session is required to load a flow graph.")

    from app.models.flow import Edge, Flow, Node
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    try:
        flow_uuid = uuid.UUID(str(flow_id))
    except (TypeError, ValueError) as exc:
        raise FlowEngineError(f"Invalid flow_id: {flow_id}") from exc

    result = await db.execute(
        select(Flow)
        .where(Flow.id == flow_uuid)
        .options(selectinload(Flow.nodes), selectinload(Flow.edges))
    )
    flow = result.scalar_one_or_none()
    if flow is None:
        raise FlowEngineError(f"Flow '{flow_id}' not found.")

    snapshot = flow.graph_snapshot if isinstance(flow.graph_snapshot, dict) else {}
    if snapshot.get("nodes") and snapshot.get("edges") is not None:
        return {
            "nodes": list(snapshot.get("nodes") or []),
            "edges": list(snapshot.get("edges") or []),
        }

    nodes = [
        {
            "id": n.canvas_id or str(n.id),
            "type": n.type,
            "data": n.data or {},
            "position": n.position or {},
        }
        for n in (flow.nodes or [])
    ]
    edges = [
        {
            "id": e.canvas_id or str(e.id),
            "source": e.source,
            "target": e.target,
            "type": e.type,
            "data": e.data or {},
        }
        for e in (flow.edges or [])
    ]
    return {"nodes": nodes, "edges": edges}


async def execute_flow(
    db: AsyncSession | None,
    flow_id: str,
    session_id: str,
    initial_input: dict[str, Any] | None = None,
    *,
    graph: dict[str, Any] | None = None,
    session_manager: FlowSessionManager | None = None,
    max_execution_steps: int | None = None,
    raise_on_loop: bool = True,
    organization_id: uuid.UUID | None = None,
    node_registry: Any | None = None,
) -> FlowExecutionResult:
    """
    Execute / resume a flow for ``session_id``.

    Parameters
    ----------
    graph:
        Optional in-memory graph (tests / dry-run). When omitted, loaded from DB.
    raise_on_loop:
        If True (default), re-raise ``FlowExecutionLoopError`` after logging.
        If False, return a safe ``status=loop_error`` result.
    """
    initial_input = dict(initial_input or {})
    resolved_graph = graph if graph is not None else await load_flow_graph(db, flow_id)

    manager = session_manager or FlowSessionManager()
    session = await manager.get_or_create(
        session_id=session_id,
        flow_id=str(flow_id),
        initial_variables={
            k: v
            for k, v in initial_input.items()
            if not str(k).startswith("__")
        },
    )

    engine = FlowExecutionEngine(
        manager,
        max_execution_steps=max_execution_steps,
        node_registry=node_registry,
    )
    logger.info(
        "FlowExecutor.start | flow_id={flow} session={sid} cursor={cursor}",
        flow=flow_id,
        sid=session_id,
        cursor=session.current_node_id,
    )

    run_kwargs = {
        "graph": resolved_graph,
        "session": session,
        "initial_input": initial_input,
        "db": db,
        "organization_id": organization_id,
    }

    try:
        if raise_on_loop:
            result = await engine.run(**run_kwargs)
        else:
            result = await engine.run_safe(**run_kwargs)
    except FlowExecutionLoopError:
        raise
    except FlowEngineError:
        raise
    except Exception as exc:
        logger.exception(
            "FlowExecutor.failed | flow_id={flow} session={sid} error={error}",
            flow=flow_id,
            sid=session_id,
            error=str(exc),
        )
        raise FlowEngineError(str(exc)) from exc

    logger.info(
        "FlowExecutor.done | flow_id={flow} session={sid} status={status} steps={steps}",
        flow=flow_id,
        sid=session_id,
        status=result.status,
        steps=result.steps_executed,
    )
    return result
