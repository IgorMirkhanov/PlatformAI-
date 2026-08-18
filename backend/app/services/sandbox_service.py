from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.flow_cache import published_flow_cache
from app.models.core_models import Bot, BotFlow
from app.schemas.sandbox_schemas import SandboxChatResponse, SandboxClearResponse
from app.services.ai_orchestrator import AIOrchestrator
from app.services.execution_trace import ExecutionTraceBuilder
from app.services.flow_executor import FlowExecutor


@dataclass
class SandboxSession:
    session_id: str
    bot_id: uuid.UUID
    current_step_id: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    variables: dict[str, object] = field(default_factory=dict)


class SandboxService:
    """In-memory sandbox sessions for internal agent testing without production chat writes."""

    def __init__(self) -> None:
        self._sessions: dict[str, SandboxSession] = {}

    def _session_key(self, bot_id: uuid.UUID, session_id: str) -> str:
        return f"{bot_id}:{session_id}"

    def get_or_create_session(
        self,
        bot_id: uuid.UUID,
        session_id: str | None = None,
    ) -> SandboxSession:
        resolved_session_id = session_id or str(uuid.uuid4())
        key = self._session_key(bot_id, resolved_session_id)
        existing = self._sessions.get(key)
        if existing is not None:
            return existing

        session = SandboxSession(session_id=resolved_session_id, bot_id=bot_id)
        self._sessions[key] = session
        return session

    def clear_session(self, bot_id: uuid.UUID, session_id: str | None = None) -> SandboxClearResponse:
        if session_id:
            key = self._session_key(bot_id, session_id)
            self._sessions.pop(key, None)
            return SandboxClearResponse(bot_id=bot_id, session_id=session_id)

        prefix = f"{bot_id}:"
        removed = [key for key in self._sessions if key.startswith(prefix)]
        for key in removed:
            self._sessions.pop(key, None)

        new_session_id = str(uuid.uuid4())
        return SandboxClearResponse(
            bot_id=bot_id,
            session_id=new_session_id,
            message="All sandbox sessions cleared for this bot.",
        )

    async def _load_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Bot:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bot with id '{bot_id}' not found.",
            )
        return bot

    async def _load_published_flow(self, db: AsyncSession, bot_id: uuid.UUID) -> BotFlow:
        cached = published_flow_cache.get(bot_id)
        if cached is not None and cached.is_published:
            # Hydrate a lightweight ORM-compatible stand-in for the executor path.
            flow = BotFlow(
                id=cached.flow_id,
                bot_id=cached.bot_id,
                title=cached.title,
                graph_data=cached.graph_data,
                is_published=True,
                updated_at=cached.updated_at,
            )
            return flow

        result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == bot_id, BotFlow.is_published.is_(True))
            .order_by(BotFlow.updated_at.desc())
            .limit(1),
        )
        flow = result.scalar_one_or_none()
        if flow is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No published flow found for this bot. Publish a scenario first.",
            )

        graph_data = flow.graph_data if isinstance(flow.graph_data, dict) else {}
        published_flow_cache.put_from_orm(
            flow_id=flow.id,
            bot_id=bot_id,
            title=flow.title,
            graph_data=graph_data,
            is_published=True,
            updated_at=flow.updated_at,
        )
        return flow

    @staticmethod
    def _format_response_message(text: str, buttons: list[dict[str, str]]) -> str:
        cleaned = text.strip()
        if not buttons:
            return cleaned

        options = "\n".join(f"• {button.get('text', '')}" for button in buttons if button.get("text"))
        if not options:
            return cleaned
        if cleaned:
            return f"{cleaned}\n\n{options}"
        return options

    async def process_message(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        message_text: str,
        *,
        session_id: str | None = None,
    ) -> SandboxChatResponse:
        trace = ExecutionTraceBuilder()
        session = self.get_or_create_session(bot_id, session_id)
        bot = await self._load_bot(db, bot_id)
        flow = await self._load_published_flow(db, bot_id)

        graph_data = flow.graph_data if isinstance(flow.graph_data, dict) else {}
        if not graph_data:
            trace.record_error("empty_graph")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Published flow contains empty graph data.",
            )

        bot_config = FlowExecutor.build_bot_config(bot)
        bot_config["simulation_mode"] = True

        executor = FlowExecutor()
        try:
            next_node = executor.find_next_node(
                graph_data=graph_data,
                current_step_id=session.current_step_id or None,
                incoming_message=message_text,
                bot_config=bot_config,
                trace=trace,
            )
        except Exception as exc:
            logger.exception(
                "SandboxService.executor_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            trace.record_error(str(exc))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Sandbox flow execution failed.",
            ) from exc

        previous_step = session.current_step_id
        node_id = str(next_node["node_id"])
        error = next_node.get("error")

        if error == "button_mismatch" and previous_step:
            session.current_step_id = previous_step
        elif node_id == FlowExecutor.WAITING_STEP_ID:
            session.current_step_id = previous_step or node_id
        else:
            session.current_step_id = node_id

        if previous_step and session.current_step_id and previous_step != session.current_step_id:
            trace.record_transition(
                previous_step,
                session.current_step_id,
                via_handle=str(next_node.get("matched_button_id") or "") or None,
            )
        trace.set_current_node(session.current_step_id or node_id)

        response_text = str(next_node.get("text") or "")
        raw_buttons = next_node.get("buttons") or []
        buttons = [
            {"id": str(btn.get("id", index)), "text": str(btn.get("text", ""))}
            for index, btn in enumerate(raw_buttons)
            if isinstance(btn, dict)
        ]

        if next_node.get("requires_ai") or next_node.get("node_type") == "ai_agent":
            orchestrator = AIOrchestrator()
            node_data = next_node.get("data") or {}
            if not isinstance(node_data, dict):
                node_data = {}

            node_model = (
                node_data.get("model_name")
                or node_data.get("llm_model_name")
                or next_node.get("llm_model_name")
                or bot.llm_model_name
                or AIOrchestrator.DEFAULT_FAST_MODEL
            )
            node_temperature = (
                node_data.get("temperature")
                if node_data.get("temperature") is not None
                else next_node.get("llm_temperature")
                if next_node.get("llm_temperature") is not None
                else bot.llm_temperature
            )

            ai_response, _metrics = await orchestrator.generate_ai_response_with_trace(
                current_node_data=node_data,
                incoming_message=message_text,
                db_session=db,
                history=session.history,
                trace=trace,
                model_name=str(node_model),
                temperature=float(node_temperature),
                global_prompt=str(bot_config.get("prompt_instructions") or ""),
                bot_id=bot_id,
                node_id=str(next_node.get("node_id") or ""),
                channel="sandbox",
            )
            response_text = ai_response

        formatted_message = self._format_response_message(response_text, buttons)

        session.history.append({"role": "user", "content": message_text.strip()})
        if formatted_message.strip():
            session.history.append({"role": "assistant", "content": formatted_message.strip()})

        limit = 20
        if len(session.history) > limit:
            session.history = session.history[-limit:]

        # Persist lightweight execution variables on the session for multi-turn context.
        if not hasattr(session, "variables") or session.variables is None:
            session.variables = {}
        session.variables.update(
            {
                "last_user_message": message_text.strip(),
                "last_bot_message": formatted_message.strip(),
                "current_step_id": session.current_step_id,
                "turn_count": int(session.variables.get("turn_count", 0)) + 1,
            }
        )

        logger.info(
            "SandboxService.message_processed | bot_id={bot_id} session_id={session_id} step={step}",
            bot_id=bot_id,
            session_id=session.session_id,
            step=session.current_step_id,
        )

        trace_model = trace.to_model()
        llm = trace_model.llm_metrics
        input_tokens = int(llm.input_tokens) if llm else 0
        output_tokens = int(llm.output_tokens) if llm else 0
        tokens_used = int(llm.total_tokens) if llm else (input_tokens + output_tokens)

        credits_charged = 0
        if llm is not None and bot_id is not None:
            try:
                from app.services.llm.pricing import calculate_cost

                model_name = str(llm.model_name or bot.llm_model_name or "gpt-4o-mini")
                credits_charged = int(
                    calculate_cost(model_name, input_tokens, output_tokens)
                )
            except Exception:
                credits_charged = 0

        execution_context = {
            "session_id": session.session_id,
            "bot_id": str(bot_id),
            "current_step_id": session.current_step_id or None,
            "history": list(session.history),
            "variables": dict(getattr(session, "variables", {}) or {}),
            "node_id": str(next_node.get("node_id") or ""),
            "node_type": str(next_node.get("node_type") or ""),
        }

        return SandboxChatResponse(
            message=formatted_message,
            trace=trace_model,
            session_id=session.session_id,
            current_step_id=session.current_step_id or None,
            node_execution_trace=list(trace_model.nodes_triggered),
            execution_context=execution_context,
            tokens_used=tokens_used,
            credits_charged=credits_charged,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


sandbox_service = SandboxService()
