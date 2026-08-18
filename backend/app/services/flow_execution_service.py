"""Unified async flow execution engine with optional streaming callbacks.

Wraps production ``FlowExecutor`` (``flow_parser``) and emits structured events
for HTTP execute + WebSocket preview clients.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.flow_cache import published_flow_cache
from app.models.core_models import Bot, BotFlow
from app.models.saas_metering import UsageMetricType
from app.services.flow_parser import FlowExecutionResult, FlowExecutor
from app.services.usage_service import usage_service

StreamCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass
class ExecutionSession:
    session_id: str
    bot_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    current_step_id: str = ""
    variables: dict[str, Any] = field(default_factory=dict)
    message_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FlowExecuteResponse:
    session_id: str
    bot_id: uuid.UUID
    reply_text: str
    current_step_id: str
    is_waiting: bool
    nodes_visited: list[str]
    variables: dict[str, Any]
    error: str | None = None
    handoff: bool = False


class FlowExecutionService:
    """Sessionful graph runner with stream events + usage metering."""

    def __init__(self) -> None:
        self._sessions: dict[str, ExecutionSession] = {}

    def get_or_create_session(
        self,
        *,
        bot_id: uuid.UUID,
        session_id: str | None = None,
        organization_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ) -> ExecutionSession:
        sid = session_id or str(uuid.uuid4())
        key = f"{bot_id}:{sid}"
        existing = self._sessions.get(key)
        if existing is not None:
            return existing
        session = ExecutionSession(
            session_id=sid,
            bot_id=bot_id,
            organization_id=organization_id,
            user_id=user_id,
        )
        self._sessions[key] = session
        return session

    def get_session(self, session_id: str) -> ExecutionSession | None:
        for session in self._sessions.values():
            if session.session_id == session_id:
                return session
        return None

    async def _emit(self, callback: StreamCallback | None, event: dict[str, Any]) -> None:
        if callback is None:
            return
        result = callback(event)
        if hasattr(result, "__await__"):
            await result  # type: ignore[misc]

    async def _load_graph(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        use_draft: bool,
    ) -> dict[str, Any]:
        cached = published_flow_cache.get(bot_id)
        if cached is not None and cached.is_published and isinstance(cached.graph_data, dict):
            return dict(cached.graph_data)

        result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == bot_id, BotFlow.is_published.is_(True))
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        flow = result.scalar_one_or_none()
        if flow is None and use_draft:
            result = await db.execute(
                select(BotFlow)
                .where(BotFlow.bot_id == bot_id)
                .order_by(BotFlow.updated_at.desc())
                .limit(1)
            )
            flow = result.scalar_one_or_none()
        if flow is None or not isinstance(flow.graph_data, dict) or not flow.graph_data:
            raise ValueError("No published flow for bot.")
        published_flow_cache.put_from_orm(
            flow_id=flow.id,
            bot_id=bot_id,
            title=flow.title,
            graph_data=flow.graph_data,
            is_published=bool(flow.is_published),
            updated_at=flow.updated_at,
        )
        return dict(flow.graph_data)

    async def execute_turn(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        message: str,
        session_id: str | None = None,
        client_id: uuid.UUID | None = None,
        on_event: StreamCallback | None = None,
        use_draft: bool = False,
    ) -> FlowExecuteResponse:
        bot = await db.get(Bot, bot_id)
        if bot is None or getattr(bot, "deleted_at", None) is not None:
            raise ValueError("Bot not found.")

        from app.services.quota_service import QuotaExceeded, quota_service

        try:
            org_id = getattr(bot, "organization_id", None)
            if org_id is None:
                org_id = bot.user_id  # legacy bots without org
            await quota_service.assert_message_quota(db, org_id)
        except QuotaExceeded:
            raise

        session = self.get_or_create_session(
            bot_id=bot_id,
            session_id=session_id,
            organization_id=getattr(bot, "organization_id", None),
            user_id=bot.user_id,
        )
        session.message_count += 1

        await self._emit(
            on_event,
            {
                "type": "start",
                "session_id": session.session_id,
                "bot_id": str(bot_id),
                "message": message,
            },
        )

        graph = await self._load_graph(db, bot_id, use_draft=use_draft)
        executor = FlowExecutor(graph)

        nodes_visited: list[str] = []
        handoff = False
        error: str | None = None
        reply = ""
        waiting = False

        try:
            result: FlowExecutionResult = await executor.execute(
                current_step_id=session.current_step_id or None,
                incoming_message=message,
                context={"variables": dict(session.variables), "channel": "execute"},
                db=db,
                bot_id=bot_id,
                client_id=client_id,
            )
            if result.node_id:
                nodes_visited = [result.node_id]
                await self._emit(
                    on_event,
                    {
                        "type": "node_enter",
                        "node_id": result.node_id,
                        "node_type": result.node_type,
                    },
                )

            reply = (result.text or "").strip()
            waiting = bool(result.is_waiting)
            error = result.error
            session.current_step_id = result.node_id or session.current_step_id

            if result.node_type in {"human_handoff", "handoff"}:
                handoff = True
                data = result.data if isinstance(result.data, dict) else {}
                if data.get("pause_bot", True) and client_id is not None:
                    from app.models.core_models import Client

                    client = await db.get(Client, client_id)
                    if client is not None:
                        client.is_paused_by_operator = True

            vars_attr = getattr(executor, "variables", None)
            if isinstance(vars_attr, dict):
                session.variables.update(vars_attr)

            if reply:
                await self._emit(
                    on_event,
                    {
                        "type": "message",
                        "text": reply,
                        "node_id": result.node_id,
                        "node_type": result.node_type,
                    },
                )

        except Exception as exc:
            logger.exception(
                "FlowExecution.failed | bot_id={bot_id} session={sid} error={error}",
                bot_id=bot_id,
                sid=session.session_id,
                error=str(exc),
            )
            error = str(exc)
            await self._emit(on_event, {"type": "error", "error": error})
            raise

        try:
            await usage_service.record_and_debit(
                db,
                user_id=bot.user_id,
                organization_id=session.organization_id,
                bot_id=bot_id,
                metric_type=UsageMetricType.MESSAGE_IN,
                quantity=1,
                unit_cost=Decimal("0"),
                debit_wallet=False,
                meta={"session_id": session.session_id, "channel": "execute"},
            )
            if reply:
                await usage_service.record_and_debit(
                    db,
                    user_id=bot.user_id,
                    organization_id=session.organization_id,
                    bot_id=bot_id,
                    metric_type=UsageMetricType.MESSAGE_OUT,
                    quantity=1,
                    unit_cost=Decimal("0"),
                    debit_wallet=False,
                    meta={"session_id": session.session_id},
                )
        except Exception as exc:
            logger.debug("FlowExecution.usage_skip | error={error}", error=str(exc))

        await self._emit(
            on_event,
            {
                "type": "done",
                "session_id": session.session_id,
                "current_step_id": session.current_step_id,
                "nodes_visited": nodes_visited,
                "handoff": handoff,
                "is_waiting": waiting,
            },
        )

        return FlowExecuteResponse(
            session_id=session.session_id,
            bot_id=bot_id,
            reply_text=reply,
            current_step_id=session.current_step_id,
            is_waiting=waiting,
            nodes_visited=nodes_visited,
            variables=dict(session.variables),
            error=error,
            handoff=handoff,
        )


flow_execution_service = FlowExecutionService()
