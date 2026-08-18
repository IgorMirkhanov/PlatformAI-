"""Celery tasks for long-running / async flow graph execution."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger

from app.core.celery_app import celery_app
from app.schemas.bot_graph import BotGraph


async def _execute_graph_async(
    *,
    bot_id: str,
    message: str,
    graph_data: dict[str, Any] | None,
    variables: dict[str, Any] | None,
    client_id: str | None,
    current_step_id: str | None,
) -> dict[str, Any]:
    from app.core.database import async_session_factory
    from app.services.bot_management_service import bot_management_service
    from app.services.flow_parser import FlowExecutor

    graph = graph_data
    if not graph:
        async with async_session_factory() as db:
            flow_response = await bot_management_service.get_bot_flow(db, uuid.UUID(bot_id))
            raw = getattr(flow_response, "graph_data", None)
            if hasattr(raw, "model_dump"):
                graph = raw.model_dump()
            elif isinstance(raw, dict):
                graph = raw
            else:
                graph = None

    validated = BotGraph.from_raw(graph if isinstance(graph, dict) else {})
    compiled = {
        "nodes": [n.model_dump() for n in validated.nodes],
        "edges": [e.model_dump(by_alias=True) for e in validated.edges],
    }
    executor = FlowExecutor(compiled)
    if variables:
        executor.variables.update(variables)

    bot_uuid = uuid.UUID(bot_id)
    client_uuid = uuid.UUID(client_id) if client_id else None

    async with async_session_factory() as db:
        result = await executor.execute(
            current_step_id=current_step_id,
            incoming_message=message,
            context=dict(variables or {}),
            db=db,
            bot_id=bot_uuid,
            client_id=client_uuid,
        )

    return {
        "ok": True,
        "bot_id": bot_id,
        "node_id": getattr(result, "node_id", None),
        "node_type": getattr(result, "node_type", None),
        "text": getattr(result, "text", None),
        "is_waiting": getattr(result, "is_waiting", None),
        "pointer": getattr(executor, "pointer", None),
        "variables": dict(getattr(executor, "variables", {}) or {}),
        "error": getattr(result, "error", None),
    }


@celery_app.task(
    name="app.tasks.flow_tasks.execute_flow_task",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def execute_flow_task(
    self,
    bot_id: str,
    message: str,
    graph_data: dict[str, Any] | None = None,
    variables: dict[str, Any] | None = None,
    client_id: str | None = None,
    current_step_id: str | None = None,
) -> dict[str, Any]:
    """
    Run ``FlowExecutor`` against a BotGraph (or the bot's saved/published graph).

    Prefer inbound webhook workers for messenger traffic; use this for
    batch/manual/API-triggered long runs.
    """
    logger.info(
        "Flow.execute_task_start | bot_id={bot_id} task_id={task_id}",
        bot_id=bot_id,
        task_id=self.request.id,
    )
    try:
        return asyncio.run(
            _execute_graph_async(
                bot_id=bot_id,
                message=message,
                graph_data=graph_data,
                variables=variables,
                client_id=client_id,
                current_step_id=current_step_id,
            )
        )
    except Exception as exc:
        logger.exception(
            "Flow.execute_task_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise self.retry(exc=exc) from exc
