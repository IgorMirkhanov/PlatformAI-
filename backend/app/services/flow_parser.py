"""Graph traversal / execution engine for compiled React Flow JSON graphs.

``FlowExecutor(compiled_graph_json)`` walks the active node pointer, evaluates
LLM / Condition / CRM node types, and advances along edges until a user-facing
response is ready (or the graph waits / terminates).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


@dataclass
class FlowExecutionResult:
    """Outcome of a sequential graph walk for one inbound message."""

    node_id: str
    node_type: str
    text: str = ""
    buttons: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    is_waiting: bool = False
    is_terminal: bool = False
    bot_silent: bool = False
    requires_ai: bool = False
    crm_action: dict[str, Any] | None = None
    error: str | None = None
    matched_button_id: str | None = None
    media_attachments: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "text": self.text,
            "buttons": self.buttons,
            "data": self.data,
            "variables": self.variables,
            "is_waiting": self.is_waiting,
            "is_terminal": self.is_terminal,
            "bot_silent": self.bot_silent,
            "requires_ai": self.requires_ai,
            "crm_action": self.crm_action,
            "error": self.error,
            "matched_button_id": self.matched_button_id,
            "media_attachments": self.media_attachments,
        }


class FlowExecutor:
    """
    Lightning graph parser / runner.

    Instantiated with a compiled ``{nodes, edges}`` document from PostgreSQL /
    the published-flow cache, then executed against a session context pointer
    (``current_step_id``) and inbound user message.
    """

    START_ALIASES: frozenset[str | None] = frozenset({"", "root", "welcome", None})
    WAITING_STEP_ID = "__waiting__"
    TERMINAL_STEP_ID = "__terminal__"
    MAX_HOPS = 32

    def __init__(self, compiled_graph_json: dict[str, Any] | None) -> None:
        graph = compiled_graph_json if isinstance(compiled_graph_json, dict) else {}
        self.raw_graph = graph
        self.nodes: list[dict[str, Any]] = [
            n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("id")
        ]
        self.edges: list[dict[str, Any]] = [
            e for e in (graph.get("edges") or []) if isinstance(e, dict) and e.get("source")
        ]
        self.nodes_by_id: dict[str, dict[str, Any]] = {
            str(node["id"]): node for node in self.nodes
        }
        self.edges_by_source: dict[str, list[dict[str, Any]]] = {}
        for edge in self.edges:
            self.edges_by_source.setdefault(str(edge["source"]), []).append(edge)

        self.variables: dict[str, Any] = {}
        self.pointer: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        *,
        current_step_id: str | None,
        incoming_message: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
    ) -> FlowExecutionResult:
        """
        Traverse the compiled graph from ``current_step_id`` until a response
        payload is ready for the messenger channel.
        """
        ctx = dict(context or {})
        self.variables = dict(ctx.get("variables") or {})
        self.variables.setdefault("message", incoming_message)
        self.variables.setdefault("user_name", ctx.get("user_name") or "")
        self.variables.setdefault("channel", ctx.get("channel") or "webhook")
        self.variables.setdefault("phone", ctx.get("phone") or ctx.get("external_id") or "")
        self.variables.setdefault("external_id", ctx.get("external_id") or "")
        self.variables.setdefault("tags", ctx.get("tags") or [])
        self.variables.setdefault("rag_context", "")
        self.variables.setdefault("rag_chunks", [])

        # Agent-level prompt from «Промптинг» tab (bot.prompt_instructions).
        bot_config = ctx.get("bot_config") if isinstance(ctx.get("bot_config"), dict) else {}
        self.bot_config: dict[str, Any] = dict(bot_config or {})
        agent_prompt = str(self.bot_config.get("prompt_instructions") or "").strip()
        if agent_prompt:
            self.variables["prompt_instructions"] = agent_prompt

        message = (incoming_message or "").strip()
        step = (current_step_id or "").strip() or None

        logger.info(
            "FlowParser.start | step={step!r} nodes={nodes} message_len={length}",
            step=step,
            nodes=len(self.nodes),
            length=len(message),
        )

        if not self.nodes:
            return FlowExecutionResult(
                node_id=self.WAITING_STEP_ID,
                node_type="waiting",
                text="Сценарий бота ещё не настроен.",
                is_waiting=True,
                error="empty_graph",
            )

        active = self.locate_active_node(step)
        if active is None:
            return FlowExecutionResult(
                node_id=self.WAITING_STEP_ID,
                node_type="waiting",
                text="Не удалось определить начало сценария.",
                is_waiting=True,
                error="no_start_node",
            )

        result: FlowExecutionResult | None = None

        # Leaving the current node (button / condition / LLM turn) before entry hops.
        if not self._is_start_state(step):
            result = await self._advance_from_current(
                active,
                message=message,
                db=db,
                bot_id=bot_id,
                client_id=client_id,
            )
            if self._should_return_to_user(result, active):
                self.pointer = result.node_id
                result.variables = dict(self.variables)
                return result
            nxt = self.nodes_by_id.get(result.node_id)
            if nxt is not None:
                active = nxt

        hops = 0
        while hops < self.MAX_HOPS:
            hops += 1
            result = await self._enter_node(
                active,
                message=message,
                db=db,
                bot_id=bot_id,
                client_id=client_id,
                matched_button_id=None,
            )

            # Silent handoff to another node (condition/crm/trigger passthrough).
            if result.bot_silent and result.node_id != str(active.get("id")):
                nxt = self.nodes_by_id.get(result.node_id)
                if nxt is None:
                    break
                active = nxt
                continue

            if self._should_return_to_user(result, active):
                break

            nxt = self._follow_default_edge(active)
            if nxt is None:
                break
            active = nxt

        assert result is not None
        self.pointer = result.node_id
        result.variables = dict(self.variables)
        logger.info(
            "FlowParser.complete | pointer={pointer} type={type} hops={hops} waiting={waiting}",
            pointer=result.node_id,
            type=result.node_type,
            hops=hops,
            waiting=result.is_waiting,
        )
        return result

    def locate_active_node(self, current_step_id: str | None) -> dict[str, Any] | None:
        """Locate the active node based on the current context pointer."""
        step = (current_step_id or "").strip()
        if self._is_start_state(step):
            return self._find_start_node()
        node = self.nodes_by_id.get(step)
        if node is not None:
            return node
        logger.warning("FlowParser.unknown_step | step={step} — reset to start", step=step)
        return self._find_start_node()

    # ------------------------------------------------------------------
    # Node evaluation
    # ------------------------------------------------------------------

    async def _enter_node(
        self,
        node: dict[str, Any],
        *,
        message: str,
        db: AsyncSession | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        matched_button_id: str | None,
    ) -> FlowExecutionResult:
        node_type = self._node_type(node)
        node_id = str(node["id"])
        data = node.get("data") if isinstance(node.get("data"), dict) else {}

        logger.debug(
            "FlowParser.enter | node_id={node_id} type={node_type}",
            node_id=node_id,
            node_type=node_type,
        )

        if node_type in {"trigger", "input", "start"}:
            return self._passthrough(node, message)

        if node_type in {"ai_agent", "llm"}:
            return await self._eval_llm_node(
                node,
                message=message,
                db=db,
                bot_id=bot_id,
                client_id=client_id,
            )

        if node_type in {"knowledge_search", "rag", "knowledge"}:
            return await self._eval_knowledge_search_node(
                node,
                message=message,
                bot_id=bot_id,
            )

        if node_type == "condition":
            return await self._eval_condition_node(node, message=message)

        if node_type in {"crm_action", "crm"}:
            return await self._eval_crm_node(
                node,
                db=db,
                bot_id=bot_id,
                client_id=client_id,
            )

        if node_type == "text_message":
            return FlowExecutionResult(
                node_id=node_id,
                node_type=node_type,
                text=self._render_template(str(data.get("text") or "")),
                buttons=list(data.get("buttons") or []),
                data=data,
                matched_button_id=matched_button_id,
                is_waiting=bool(data.get("buttons")),
            )

        if node_type == "api_request":
            return await self._eval_api_request_node(node, message=message)

        if node_type == "loop":
            return await self._eval_loop_node(node, message=message)

        if node_type in {"human_handoff", "handoff"}:
            return self._eval_human_handoff_node(node)

        # Unknown node — surface data text if present, otherwise wait.
        return FlowExecutionResult(
            node_id=node_id,
            node_type=node_type,
            text=str(data.get("text") or data.get("label") or ""),
            data=data,
            is_waiting=True,
            error="unsupported_node_type",
        )

    async def _advance_from_current(
        self,
        current: dict[str, Any],
        *,
        message: str,
        db: AsyncSession | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
    ) -> FlowExecutionResult:
        node_type = self._node_type(current)
        node_id = str(current["id"])
        data = current.get("data") if isinstance(current.get("data"), dict) else {}
        outgoing = self.edges_by_source.get(node_id, [])

        # Conversational LLM stays on the same node and regenerates.
        if node_type in {"ai_agent", "llm"}:
            return await self._eval_llm_node(
                current,
                message=message,
                db=db,
                bot_id=bot_id,
                client_id=client_id,
            )

        if node_type in {"knowledge_search", "rag", "knowledge"}:
            return await self._eval_knowledge_search_node(
                current,
                message=message,
                bot_id=bot_id,
            )

        if node_type == "condition":
            return await self._eval_condition_node(current, message=message)

        if node_type == "loop":
            return await self._eval_loop_node(current, message=message)

        if node_type in {"human_handoff", "handoff"}:
            return self._eval_human_handoff_node(current)

        if node_type in {"crm_action", "crm"}:
            return await self._eval_crm_node(
                current,
                db=db,
                bot_id=bot_id,
                client_id=client_id,
            )

        if node_type == "text_message":
            buttons = list(data.get("buttons") or [])
            if buttons:
                matched = self._match_button(buttons, message)
                if matched is None:
                    return FlowExecutionResult(
                        node_id=node_id,
                        node_type=node_type,
                        text=(
                            f"{data.get('text') or ''}\n\n"
                            "Пожалуйста, выберите один из предложенных вариантов."
                        ).strip(),
                        buttons=buttons,
                        data=data,
                        is_waiting=True,
                        error="button_mismatch",
                    )
                button_id = str(matched.get("id") or "")
                edge = self._find_edge_by_handle(outgoing, button_id) or self._find_edge_by_handle(
                    outgoing, str(matched.get("text") or "")
                )
                if edge is None and len(outgoing) == 1 and not outgoing[0].get("sourceHandle"):
                    edge = outgoing[0]
                target = self.nodes_by_id.get(str(edge["target"])) if edge else None
                if target is None:
                    return FlowExecutionResult(
                        node_id=node_id,
                        node_type=node_type,
                        text=str(data.get("text") or ""),
                        buttons=buttons,
                        data=data,
                        is_waiting=True,
                        error="no_edge_for_button",
                        matched_button_id=button_id,
                    )
                return await self._enter_node(
                    target,
                    message=message,
                    db=db,
                    bot_id=bot_id,
                    client_id=client_id,
                    matched_button_id=button_id,
                )

            if outgoing:
                target = self.nodes_by_id.get(str(outgoing[0]["target"]))
                if target is not None:
                    return await self._enter_node(
                        target,
                        message=message,
                        db=db,
                        bot_id=bot_id,
                        client_id=client_id,
                        matched_button_id=None,
                    )

            return FlowExecutionResult(
                node_id=node_id,
                node_type=node_type,
                text=str(data.get("text") or "Диалог завершён. Спасибо за обращение!"),
                data=data,
                is_terminal=True,
            )

        # Default linear advance
        if outgoing:
            target = self.nodes_by_id.get(str(outgoing[0]["target"]))
            if target is not None:
                return await self._enter_node(
                    target,
                    message=message,
                    db=db,
                    bot_id=bot_id,
                    client_id=client_id,
                    matched_button_id=None,
                )

        return FlowExecutionResult(
            node_id=node_id,
            node_type=node_type,
            text=str(data.get("text") or "Диалог завершён."),
            data=data,
            is_terminal=True,
        )

    async def _eval_knowledge_search_node(
        self,
        node: dict[str, Any],
        *,
        message: str,
        bot_id: uuid.UUID | None,
    ) -> FlowExecutionResult:
        """Run Chroma similarity search and stash chunks into session variables.

        Downstream LLM prompts can interpolate ``{{rag_context}}`` (joined text)
        or read ``rag_chunks`` (list) from the shared variable bag.
        """
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_id = str(node["id"])

        top_k = int(data.get("top_k") or 3)
        top_k = max(1, min(10, top_k))
        query_variable = str(data.get("query_variable") or "message").strip() or "message"
        output_variable = str(data.get("output_variable") or "rag_context").strip() or "rag_context"
        knowledge_base_id = str(
            data.get("knowledge_base_id") or bot_id or ""
        ).strip()

        query_raw = self.variables.get(query_variable)
        query = str(query_raw if query_raw is not None else message or "").strip()
        if not query:
            query = str(self.variables.get("message") or message or "").strip()

        chunks: list[str] = []
        if knowledge_base_id and query:
            try:
                from app.core.vector_db import similarity_search

                chunks = await similarity_search(
                    knowledge_base_id,
                    query,
                    top_k=top_k,
                )
            except Exception as exc:
                logger.exception(
                    "FlowParser.knowledge_search_failed | node_id={node_id} kb={kb} error={error}",
                    node_id=node_id,
                    kb=knowledge_base_id,
                    error=str(exc),
                )
                chunks = []
        else:
            logger.warning(
                "FlowParser.knowledge_search_skipped | node_id={node_id} kb={kb!r} query_len={qlen}",
                node_id=node_id,
                kb=knowledge_base_id,
                qlen=len(query),
            )

        joined = "\n\n".join(chunk.strip() for chunk in chunks if chunk and str(chunk).strip())
        self.variables[output_variable] = joined
        self.variables["rag_context"] = joined
        self.variables["rag_chunks"] = list(chunks)

        logger.info(
            "FlowParser.knowledge_search | node_id={node_id} kb={kb} top_k={top_k} hits={hits} out={out}",
            node_id=node_id,
            kb=knowledge_base_id,
            top_k=top_k,
            hits=len(chunks),
            out=output_variable,
        )

        outgoing = self.edges_by_source.get(node_id, [])
        if outgoing:
            target = self.nodes_by_id.get(str(outgoing[0]["target"]))
            if target is not None:
                return FlowExecutionResult(
                    node_id=str(target["id"]),
                    node_type=self._node_type(target),
                    text="",
                    data=target.get("data") if isinstance(target.get("data"), dict) else {},
                    bot_silent=True,
                )

        return FlowExecutionResult(
            node_id=node_id,
            node_type="knowledge_search",
            text="",
            data=data,
            is_waiting=True,
            error="knowledge_search_without_edge",
        )

    async def _eval_llm_node(
        self,
        node: dict[str, Any],
        *,
        message: str,
        db: AsyncSession | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
    ) -> FlowExecutionResult:
        """Resolve prompt templates and call OpenAI (gpt-4o-mini) via AIOrchestrator."""
        data = dict(node.get("data") or {})
        node_id = str(node["id"])

        prompt_context = self._render_template(str(data.get("prompt_context") or ""))
        prompt_modifier = self._render_template(str(data.get("prompt_modifier") or ""))
        bot_cfg = getattr(self, "bot_config", None) or {}
        global_prompt = str(
            data.get("global_prompt_instructions")
            or self.variables.get("prompt_instructions")
            or bot_cfg.get("prompt_instructions")
            or ""
        ).strip()
        temperature = float(
            data.get("temperature")
            if data.get("temperature") is not None
            else bot_cfg.get("llm_temperature")
            if bot_cfg.get("llm_temperature") is not None
            else 0.7
        )
        knowledge_base_id = str(data.get("knowledge_base_id") or (bot_id or "")).strip()

        node_payload = {
            **data,
            "prompt_context": prompt_context,
            "prompt_modifier": prompt_modifier,
            "global_prompt_instructions": global_prompt,
            "temperature": temperature,
            "knowledge_base_id": knowledge_base_id or str(bot_id or ""),
            "llm_model_name": (
                data.get("llm_model_name")
                or bot_cfg.get("llm_model_name")
                or "gpt-4o-mini"
            ),
        }

        text = ""
        media: list[Any] = []

        if db is not None and client_id is not None and bot_id is not None:
            try:
                from app.services.ai_orchestrator import AIOrchestrator

                orchestrator = AIOrchestrator()
                ai_result = await orchestrator.generate_ai_response(
                    client_id=client_id,
                    current_node_data=node_payload,
                    incoming_message=message,
                    db_session=db,
                    bot_id=bot_id,
                    node_id=node_id,
                    channel=str(self.variables.get("channel") or "webhook"),
                )
                if isinstance(ai_result, str):
                    text = ai_result
                else:
                    text = ai_result.text
                    media = list(ai_result.media_attachments or [])
            except Exception as exc:
                logger.exception(
                    "FlowParser.llm_orchestrator_failed | node_id={node_id} error={error}",
                    node_id=node_id,
                    error=str(exc),
                )
                text = await self._openai_fallback(
                    prompt_context,
                    prompt_modifier,
                    message,
                    temperature,
                    db=db,
                    bot_id=bot_id,
                    global_prompt=global_prompt,
                )
        else:
            text = await self._openai_fallback(
                prompt_context,
                prompt_modifier,
                message,
                temperature,
                db=db,
                bot_id=bot_id,
                global_prompt=global_prompt,
            )

        self.variables["llm_output"] = text
        self.variables["api_response"] = text

        return FlowExecutionResult(
            node_id=node_id,
            node_type="ai_agent",
            text=text,
            data=node_payload,
            requires_ai=False,
            is_waiting=True,
            media_attachments=media,
        )

    async def _openai_fallback(
        self,
        prompt_context: str,
        prompt_modifier: str,
        message: str,
        temperature: float,
        *,
        db: AsyncSession | None = None,
        bot_id: uuid.UUID | None = None,
        global_prompt: str | None = None,
    ) -> str:
        """Gateway-backed gpt-4o-mini when org context exists; direct OpenAI otherwise."""
        parts = [p.strip() for p in (global_prompt, prompt_context) if p and str(p).strip()]
        system = "\n\n".join(parts) if parts else "You are a helpful assistant."
        if prompt_modifier:
            system = f"{system}\n\n{prompt_modifier}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": message or "Hello"},
        ]
        model_name = getattr(settings, "OPENAI_FALLBACK_MODEL", None) or "gpt-4o-mini"

        if db is not None and bot_id is not None:
            try:
                from app.services.internal_llm_service import complete_for_bot

                response = await complete_for_bot(
                    db,
                    bot_id,
                    messages,
                    model_name=model_name,
                    temperature=max(0.0, min(2.0, temperature)),
                    source="flow_parser_fallback",
                )
                if response is not None and (response.content or "").strip():
                    return response.content.strip()
            except Exception as exc:
                logger.warning(
                    "FlowParser.gateway_fallback_failed | bot_id={bot_id} error={error}",
                    bot_id=bot_id,
                    error=str(exc),
                )

        if not settings.OPENAI_API_KEY:
            return "Извините, ИИ временно недоступен. Попробуйте позже."

        try:
            from openai import AsyncOpenAI

            timeout = float(getattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 20.0))
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=timeout)
            completion = await client.chat.completions.create(
                model=model_name,
                temperature=max(0.0, min(2.0, temperature)),
                messages=messages,
                timeout=timeout,
            )
            return (completion.choices[0].message.content or "").strip() or (
                "Извините, не удалось сформировать ответ."
            )
        except Exception as exc:
            logger.exception("FlowParser.openai_fallback_failed | error={error}", error=str(exc))
            return "К сожалению, сервис временно перегружен. Попробуйте написать чуть позже."

    async def _eval_condition_node(
        self,
        node: dict[str, Any],
        *,
        message: str,
    ) -> FlowExecutionResult:
        """Regex / equality matching on variable state → true/false edge."""
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_id = str(node["id"])
        matched = self._condition_matches(data, message)
        handle = "true" if matched else "false"
        self.variables["condition_result"] = matched
        self.variables["condition_handle"] = handle

        outgoing = self.edges_by_source.get(node_id, [])
        edge = self._find_edge_by_handle(outgoing, handle)
        target = self.nodes_by_id.get(str(edge["target"])) if edge else None

        logger.info(
            "FlowParser.condition | node_id={node_id} matched={matched} handle={handle} target={target}",
            node_id=node_id,
            matched=matched,
            handle=handle,
            target=target.get("id") if target else None,
        )

        if target is None:
            return FlowExecutionResult(
                node_id=node_id,
                node_type="condition",
                text="Condition evaluated without a connected branch.",
                data=data,
                is_waiting=True,
                error="condition_branch_missing",
            )

        # Return a passthrough pointing at the branch target so the hop loop enters it.
        return FlowExecutionResult(
            node_id=str(target["id"]),
            node_type=self._node_type(target),
            text="",
            data=target.get("data") if isinstance(target.get("data"), dict) else {},
            bot_silent=True,
        )

    async def _eval_loop_node(
        self,
        node: dict[str, Any],
        *,
        message: str,
    ) -> FlowExecutionResult:
        """Iterate body handle until continue_expression is false or max_iterations."""
        _ = message
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_id = str(node["id"])
        max_iter = max(1, int(data.get("max_iterations") or 5))
        counter_key = f"loop_count:{node_id}"
        count = int(self.variables.get(counter_key) or 0) + 1
        self.variables[counter_key] = count

        expr = str(data.get("continue_expression") or "true").strip().lower()
        continue_loop = expr not in {"", "false", "0", "no", "off"}
        if "{{" in expr:
            rendered = self._render_template(expr).strip().lower()
            continue_loop = rendered not in {"", "false", "0", "no", "off"}

        handle = "body" if continue_loop and count <= max_iter else "exit"
        outgoing = self.edges_by_source.get(node_id, [])
        edge = self._find_edge_by_handle(outgoing, handle)
        if edge is None and handle == "body":
            edge = self._find_edge_by_handle(outgoing, "exit")
            handle = "exit"
        target = self.nodes_by_id.get(str(edge["target"])) if edge else None

        logger.info(
            "FlowParser.loop | node_id={node_id} count={count}/{max_iter} handle={handle}",
            node_id=node_id,
            count=count,
            max_iter=max_iter,
            handle=handle,
        )

        if target is None:
            return FlowExecutionResult(
                node_id=node_id,
                node_type="loop",
                text="",
                data=data,
                is_waiting=True,
                error="loop_branch_missing",
            )

        return FlowExecutionResult(
            node_id=str(target["id"]),
            node_type=self._node_type(target),
            text="",
            data=target.get("data") if isinstance(target.get("data"), dict) else {},
            bot_silent=True,
        )

    def _eval_human_handoff_node(self, node: dict[str, Any]) -> FlowExecutionResult:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_id = str(node["id"])
        text = self._render_template(
            str(
                data.get("handoff_message")
                or "Connecting you with an operator. Please wait…"
            )
        )
        self.variables["handoff"] = True
        self.variables["handoff_queue"] = str(data.get("queue_tag") or "")
        return FlowExecutionResult(
            node_id=node_id,
            node_type="human_handoff",
            text=text,
            data=data,
            is_waiting=True,
        )

    def _condition_matches(self, data: dict[str, Any], message: str) -> bool:
        condition_type = str(data.get("condition_type") or "expression").strip()
        tags = self.variables.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        if condition_type == "customer_tag":
            required = str(data.get("tag") or "").strip().casefold()
            if not required:
                return False
            return any(str(tag).casefold() == required for tag in tags)

        if condition_type == "working_hours":
            # Soft-launch: treat as always in-hours unless schedule vars provided.
            return bool(self.variables.get("within_schedule", True))

        # expression / keyword — equality or regex against message + variable bag
        expression = str(data.get("expression") or "").strip()
        if not expression:
            return False
        if expression.casefold() in {"true", "1", "yes"}:
            return True
        if expression.casefold() in {"false", "0", "no"}:
            return False

        haystacks = [
            message,
            str(self.variables.get("message") or ""),
            str(self.variables.get("llm_output") or ""),
            str(self.variables.get("api_response") or ""),
        ]
        for hay in haystacks:
            if not hay:
                continue
            if hay.casefold() == expression.casefold():
                return True
            try:
                if re.search(expression, hay, flags=re.IGNORECASE):
                    return True
            except re.error:
                if expression.casefold() in hay.casefold():
                    return True
        return False

    async def _eval_crm_node(
        self,
        node: dict[str, Any],
        *,
        db: AsyncSession | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
    ) -> FlowExecutionResult:
        """Execute CRM Action / Custom Webhook HTTP call and map the JSON response.

        Phase A: interpolate URL / headers / body from session variables, call the
        endpoint via ``httpx`` (10s timeout), store the parsed payload under the
        configured response variable, then advance to the next connected node.
        Network / non-2xx failures never crash the flow.
        """
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_id = str(node["id"])
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        target = str(data.get("target") or params.get("target") or "").strip().lower()

        integration = str(
            data.get("integration_type") or data.get("action_type") or params.get("platform") or "custom_webhook"
        ).lower()
        method = str(data.get("method") or "POST").upper()
        if method not in {"GET", "POST", "PUT"}:
            method = "POST"
        url = self._render_template(str(data.get("url") or "").strip())
        raw_headers = data.get("headers") if isinstance(data.get("headers"), dict) else {}
        headers = {
            str(key): self._render_template(str(value))
            for key, value in raw_headers.items()
            if str(key).strip()
        }
        body_template = self._render_template(str(data.get("body_template") or ""))
        response_variable = str(data.get("response_variable") or "crm_result").strip() or "crm_result"

        action_meta = {
            "integration_type": integration,
            "method": method,
            "url": url,
            "response_variable": response_variable,
            "node_id": node_id,
            "target": target or None,
            "pipeline_id": params.get("pipeline_id") or data.get("pipeline_id"),
            "stage_id": params.get("stage_id") or data.get("stage_id"),
        }

        # Native CRM bridge — no outbound HTTP.
        if target == "internal":
            result = await self._eval_crm_internal(
                data=data,
                params=params,
                db=db,
                client_id=client_id,
            )
            self._store_crm_response(response_variable, result)
            return self._crm_continue(node_id, data, {**action_meta, "action": data.get("action")})

        # Legacy graphs without an HTTP URL still use credential-based orchestrator.
        if not url and integration in {"amocrm", "bitrix24", "wazzup"}:
            result = await self._eval_crm_legacy_orchestrator(
                node_id=node_id,
                integration=integration,
                params=params,
                data=data,
                db=db,
                bot_id=bot_id,
                client_id=client_id,
            )
            self._store_crm_response(response_variable, result)
            return self._crm_continue(node_id, data, action_meta)

        if not url:
            failure = {"success": False, "error": "CRM unreachable", "detail": "missing_endpoint_url"}
            self._store_crm_response(response_variable, failure)
            await self._log_crm_integration_error(
                db=db,
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                message="CRM Action node missing endpoint URL.",
            )
            return self._crm_continue(node_id, data, action_meta)

        result = await self._execute_crm_http(
            method=method,
            url=url,
            headers=headers,
            body_template=body_template,
            db=db,
            bot_id=bot_id,
            client_id=client_id,
            node_id=node_id,
            integration=integration,
        )
        self._store_crm_response(response_variable, result)
        return self._crm_continue(node_id, data, action_meta)

    async def _eval_crm_internal(
        self,
        *,
        data: dict[str, Any],
        params: dict[str, Any],
        db: AsyncSession | None,
        client_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        if db is None or client_id is None:
            return {
                "success": False,
                "error": "CRM internal action requires db session and client_id.",
            }
        action = str(data.get("action") or params.get("action") or "").strip()
        rendered: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str):
                rendered[key] = self._render_template(value)
            else:
                rendered[key] = value
        from app.services.crm.crm_bridge_service import crm_bridge_service

        return await crm_bridge_service.execute_internal_action(
            db,
            client_id,
            action,
            rendered,
        )

    async def _execute_crm_http(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body_template: str,
        db: AsyncSession | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        node_id: str,
        integration: str,
    ) -> dict[str, Any]:
        import json

        import httpx

        timeout = httpx.Timeout(10.0, connect=5.0)
        request_kwargs: dict[str, Any] = {"headers": headers}
        if method in {"POST", "PUT"} and body_template.strip():
            try:
                request_kwargs["json"] = json.loads(body_template)
            except json.JSONDecodeError:
                request_kwargs["content"] = body_template.encode("utf-8")
                request_kwargs["headers"] = {
                    **headers,
                    "Content-Type": headers.get("Content-Type") or "application/json",
                }

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.request(method, url, **request_kwargs)

            status_code = response.status_code
            parsed: Any
            try:
                parsed = response.json()
            except Exception:
                parsed = {"raw": response.text[:4000]}

            if 200 <= status_code < 300:
                payload: dict[str, Any]
                if isinstance(parsed, dict):
                    payload = {"success": True, "status_code": status_code, **parsed}
                else:
                    payload = {"success": True, "status_code": status_code, "data": parsed}
                logger.info(
                    "FlowParser.crm_http_ok | node_id={node_id} integration={integration} status={status}",
                    node_id=node_id,
                    integration=integration,
                    status=status_code,
                )
                return payload

            await self._log_crm_integration_error(
                db=db,
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                message=(
                    f"CRM HTTP {status_code} from {integration}: "
                    f"{str(parsed)[:500]}"
                ),
            )
            return {
                "success": False,
                "error": "CRM unreachable",
                "status_code": status_code,
                "detail": parsed,
            }
        except Exception as exc:
            logger.warning(
                "FlowParser.crm_http_failed | node_id={node_id} integration={integration} error={error}",
                node_id=node_id,
                integration=integration,
                error=str(exc),
            )
            await self._log_crm_integration_error(
                db=db,
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                message=f"CRM unreachable ({integration}): {exc}",
            )
            return {"success": False, "error": "CRM unreachable"}

    async def _eval_crm_legacy_orchestrator(
        self,
        *,
        node_id: str,
        integration: str,
        params: dict[str, Any],
        data: dict[str, Any],
        db: AsyncSession | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        action_data = {
            "platform": integration if integration in {"amocrm", "bitrix24", "wazzup"} else "amocrm",
            "pipeline_id": params.get("pipeline_id") or data.get("pipeline_id"),
            "stage_id": params.get("stage_id") or data.get("stage_id"),
            "status_id": params.get("stage_id") or data.get("stage_id"),
            "tags": params.get("tags") or [],
            "node_id": node_id,
            "provider": params.get("provider"),
            "channel_id": params.get("channel_id"),
        }
        if db is None or bot_id is None or client_id is None:
            return {"success": None, "queued": True, "error": "CRM unreachable"}

        try:
            from app.services.crm_orchestrator import crm_orchestrator

            result = await crm_orchestrator.execute_crm_action(bot_id, client_id, action_data)
            if isinstance(result, dict):
                return result
            return {"success": True, "data": result}
        except Exception as exc:
            await self._log_crm_integration_error(
                db=db,
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                message=f"CRM orchestrator failure ({integration}): {exc}",
            )
            return {"success": False, "error": "CRM unreachable"}

    def _store_crm_response(self, response_variable: str, result: dict[str, Any]) -> None:
        self.variables[response_variable] = result
        self.variables["crm_result"] = result
        # Flatten scalar top-level keys for template use: {{crm_result.id}}
        for key, value in result.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                self.variables[f"{response_variable}.{key}"] = "" if value is None else value

    def _crm_continue(
        self,
        node_id: str,
        data: dict[str, Any],
        action_meta: dict[str, Any],
    ) -> FlowExecutionResult:
        outgoing = self.edges_by_source.get(node_id, [])
        if outgoing:
            target = self.nodes_by_id.get(str(outgoing[0]["target"]))
            if target is not None:
                return FlowExecutionResult(
                    node_id=str(target["id"]),
                    node_type=self._node_type(target),
                    text="",
                    data=target.get("data") if isinstance(target.get("data"), dict) else {},
                    crm_action=action_meta,
                    bot_silent=True,
                )
        return FlowExecutionResult(
            node_id=node_id,
            node_type="crm_action",
            text="CRM action completed.",
            data=data,
            crm_action=action_meta,
            is_waiting=True,
        )

    async def _log_crm_integration_error(
        self,
        *,
        db: AsyncSession | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        node_id: str,
        message: str,
    ) -> None:
        if bot_id is None:
            logger.warning(
                "FlowParser.crm_diag_skipped | node_id={node_id} reason=no_bot message={message}",
                node_id=node_id,
                message=message[:200],
            )
            return

        from app.models.core_models import DiagnosticErrorType
        from app.services.diagnostic_log_service import diagnostic_log_service

        error_type = DiagnosticErrorType.CRM_INTEGRATION_ERROR
        try:
            if db is not None:
                await diagnostic_log_service.log(
                    db,
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=error_type,
                    error_message=message,
                    node_id=node_id,
                )
            else:
                diagnostic_log_service.schedule_log(
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=error_type,
                    error_message=message,
                    node_id=node_id,
                )
        except Exception as exc:
            # Postgres may not yet know the new enum value — fall back safely.
            logger.warning(
                "FlowParser.crm_diag_fallback | node_id={node_id} error={error}",
                node_id=node_id,
                error=str(exc),
            )
            try:
                diagnostic_log_service.schedule_log(
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=DiagnosticErrorType.CRM_DISCONNECT,
                    error_message=f"[CRM_INTEGRATION_ERROR] {message}",
                    node_id=node_id,
                )
            except Exception:
                pass

    async def _eval_api_request_node(
        self,
        node: dict[str, Any],
        *,
        message: str,
    ) -> FlowExecutionResult:
        import httpx

        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_id = str(node["id"])
        method = str(data.get("method") or "POST").upper()
        url = self._render_template(str(data.get("url") or "").strip())
        headers = data.get("headers") if isinstance(data.get("headers"), dict) else {}
        body_template = self._render_template(str(data.get("body_template") or ""))
        variable_name = str(data.get("variable_name") or "api_response")

        success = False
        payload: dict[str, Any] = {"status_code": None, "body": None, "error": None}
        if url:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
                    kwargs: dict[str, Any] = {"headers": headers}
                    if method == "POST" and body_template:
                        kwargs["content"] = body_template.replace("{{message}}", message)
                    response = await client.request(method, url, **kwargs)
                payload["status_code"] = response.status_code
                payload["body"] = response.text[:4000]
                success = 200 <= response.status_code < 300
            except Exception as exc:
                payload["error"] = str(exc)

        self.variables[variable_name] = payload.get("body")
        handle = "success" if success else "failure"
        outgoing = self.edges_by_source.get(node_id, [])
        edge = self._find_edge_by_handle(outgoing, handle)
        target = self.nodes_by_id.get(str(edge["target"])) if edge else None
        if target is not None:
            return FlowExecutionResult(
                node_id=str(target["id"]),
                node_type=self._node_type(target),
                text="",
                data=target.get("data") if isinstance(target.get("data"), dict) else {},
                bot_silent=True,
            )
        return FlowExecutionResult(
            node_id=node_id,
            node_type="api_request",
            text="API request completed without a connected branch.",
            data=data,
            is_waiting=True,
            error="api_request_branch_missing",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _passthrough(self, node: dict[str, Any], message: str) -> FlowExecutionResult:
        node_id = str(node["id"])
        outgoing = self.edges_by_source.get(node_id, [])
        if outgoing:
            target = self.nodes_by_id.get(str(outgoing[0]["target"]))
            if target is not None:
                return FlowExecutionResult(
                    node_id=str(target["id"]),
                    node_type=self._node_type(target),
                    text="",
                    data=target.get("data") if isinstance(target.get("data"), dict) else {},
                    bot_silent=True,
                )
        return FlowExecutionResult(
            node_id=node_id,
            node_type=self._node_type(node),
            text="",
            is_waiting=True,
            error="trigger_without_edge",
        )

    def _render_template(self, template: str) -> str:
        rendered = template
        for key, value in self.variables.items():
            if isinstance(value, list):
                display = "\n".join(str(item) for item in value)
            elif isinstance(value, dict):
                display = str(value)
            else:
                display = "" if value is None else str(value)
            rendered = rendered.replace(f"{{{{{key}}}}}", display)
        return rendered

    def _node_type(self, node: dict[str, Any]) -> str:
        return str(node.get("type") or "default").strip().lower()

    def _is_start_state(self, step: str | None) -> bool:
        return step in self.START_ALIASES

    def _should_return_to_user(
        self,
        result: FlowExecutionResult,
        active: dict[str, Any],
    ) -> bool:
        if result.error == "button_mismatch":
            return True
        if result.is_terminal:
            return True
        if result.bot_silent and result.node_id != str(active.get("id")):
            return False
        if result.text and not result.bot_silent:
            return True
        if result.is_waiting and result.node_type in {
            "text_message",
            "ai_agent",
            "llm",
            "waiting",
            "condition",
            "api_request",
            "crm_action",
        }:
            return True
        return False

    def _follow_default_edge(self, node: dict[str, Any]) -> dict[str, Any] | None:
        outgoing = self.edges_by_source.get(str(node["id"]), [])
        if not outgoing:
            return None
        edge = next((e for e in outgoing if not e.get("sourceHandle") and not e.get("source_handle")), outgoing[0])
        return self.nodes_by_id.get(str(edge.get("target")))

    def _find_start_node(self) -> dict[str, Any] | None:
        targets = {str(edge.get("target")) for edge in self.edges}
        # Prefer trigger / text entry nodes without incoming edges.
        for preferred in ("trigger", "text_message", "ai_agent", "llm"):
            candidates = [
                n
                for n in self.nodes
                if self._node_type(n) == preferred and str(n["id"]) not in targets
            ]
            if candidates:
                return candidates[0]
        orphans = [n for n in self.nodes if str(n["id"]) not in targets]
        if orphans:
            return orphans[0]
        return self.nodes[0] if self.nodes else None

    def _match_button(self, buttons: list[dict[str, Any]], message: str) -> dict[str, Any] | None:
        if not message:
            return None
        normalized = message.casefold()
        for button in buttons:
            label = str(button.get("text", "")).strip()
            button_id = str(button.get("id", "")).strip()
            if normalized == label.casefold() or normalized == button_id.casefold():
                return button
        return None

    def _find_edge_by_handle(
        self,
        edges: list[dict[str, Any]],
        handle: str,
    ) -> dict[str, Any] | None:
        normalized = handle.casefold()
        for edge in edges:
            source_handle = edge.get("sourceHandle") or edge.get("source_handle")
            if source_handle is None:
                continue
            if str(source_handle).casefold() == normalized:
                return edge
        return None

    @staticmethod
    def build_bot_config(bot: Any) -> dict[str, Any]:
        """Compatibility helper used by webhook / sandbox callers."""
        schedule = bot.schedule_config if isinstance(getattr(bot, "schedule_config", None), dict) else {}
        return {
            "is_active": bool(getattr(bot, "is_active", True)),
            "default_chat_state": bool(getattr(bot, "default_chat_state", True)),
            "timezone": getattr(bot, "timezone", "Asia/Almaty"),
            "schedule_config": schedule,
            "prompt_instructions": getattr(bot, "prompt_instructions", "") or "",
            "llm_model_name": getattr(bot, "llm_model_name", "gpt-4o-mini"),
            "llm_temperature": float(getattr(bot, "llm_temperature", 0.5)),
            "message_split": bool(getattr(bot, "message_split", False)),
            "message_buffer_delay": int(getattr(bot, "message_buffer_delay", 0) or 0),
            "custom_code_snippet": getattr(bot, "custom_code_snippet", "") or "",
        }
