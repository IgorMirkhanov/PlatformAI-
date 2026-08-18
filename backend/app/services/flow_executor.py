from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from app.core.rbac import Permission, assert_permission
from app.models.core_models import UserRole
from app.schemas.core_schemas import FlowGraphData
from app.services.code_execution import execute_custom_code_snippet
from app.services.diagnostic_log_service import diagnostic_log_service
from app.services.execution_trace import ExecutionTraceBuilder
from app.models.core_models import DiagnosticErrorType


class FlowExecutor:
    """State-machine engine that navigates a React Flow graph based on user input."""

    START_ALIASES: frozenset[str | None] = frozenset({"", "root", "welcome", None})
    WAITING_STEP_ID = "__waiting__"
    TERMINAL_STEP_ID = "__terminal__"
    INACTIVE_STEP_ID = "__inactive__"
    OFF_SCHEDULE_STEP_ID = "__off_schedule__"

    @staticmethod
    def assert_config_mutation_allowed(
        actor_role: UserRole | None,
        permission: Permission,
    ) -> None:
        """Guard workspace mutations invoked from flow/runtime orchestration paths."""
        if actor_role is None:
            return
        assert_permission(actor_role, permission)

    def find_next_node(
        self,
        graph_data: dict[str, Any],
        current_step_id: str | None,
        incoming_message: str,
        *,
        bot_config: dict[str, Any] | None = None,
        trace: ExecutionTraceBuilder | None = None,
    ) -> dict[str, Any]:
        """
        Resolve the next bot node given the current state and incoming user message.

        Returns a dict with keys: node_id, node_type, text, buttons, data,
        matched_button_id, is_waiting, is_terminal, error.
        """
        config = bot_config or {}
        simulation_mode = bool(config.get("simulation_mode"))
        normalized_message = incoming_message.strip()
        normalized_step = (current_step_id or "").strip()

        if not simulation_mode and config.get("is_active") is False:
            logger.warning("FlowExecutor.bot_inactive")
            inactive = self._inactive_response()
            self._trace_node(trace, inactive["node_id"], inactive["node_type"], "Bot inactive")
            return inactive

        if not simulation_mode and not self._is_within_schedule(config):
            logger.info("FlowExecutor.off_schedule | timezone={tz}", tz=config.get("timezone"))
            waiting = self._waiting_response(
                text="Бот сейчас вне рабочего расписания. Напишите позже.",
                error="off_schedule",
            )
            self._trace_node(trace, waiting["node_id"], waiting["node_type"], "Off schedule")
            return waiting

        logger.info(
            "FlowExecutor.start | step={step!r} message={message!r}",
            step=normalized_step or None,
            message=normalized_message,
        )

        try:
            graph = self._parse_graph(graph_data)
        except Exception as exc:
            logger.exception("FlowExecutor.parse_failed | error={error}", error=str(exc))
            waiting = self._waiting_response(
                text="Сценарий временно недоступен. Попробуйте позже.",
                error=f"graph_parse_error: {exc}",
            )
            if trace is not None:
                trace.record_error(str(exc))
            self._trace_node(trace, waiting["node_id"], waiting["node_type"], "Graph parse error")
            return waiting

        if not graph.nodes:
            logger.warning("FlowExecutor.empty_graph")
            waiting = self._waiting_response(
                text="Сценарий бота ещё не настроен.",
                error="empty_graph",
            )
            self._trace_node(trace, waiting["node_id"], waiting["node_type"], "Empty graph")
            return waiting

        node_index = {node.id: node for node in graph.nodes}
        edges_by_source = self._index_edges(graph.edges)

        if self._is_start_state(normalized_step):
            start_node = self._find_start_node(graph.nodes, graph.edges)
            if start_node is None:
                logger.error("FlowExecutor.no_start_node")
                return self._waiting_response(
                    text="Не удалось определить начало сценария.",
                    error="no_start_node",
                )

            logger.info(
                "FlowExecutor.start_node | node_id={node_id} type={node_type}",
                node_id=start_node.id,
                node_type=start_node.type,
            )
            return self._resolve_node_entry(
                start_node,
                matched_button_id=None,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=normalized_message,
                trace=trace,
            )

        if normalized_step not in node_index:
            logger.warning(
                "FlowExecutor.unknown_step | step={step} — resetting to start",
                step=normalized_step,
            )
            start_node = self._find_start_node(graph.nodes, graph.edges)
            if start_node is None:
                return self._waiting_response(
                    text="Сессия сброшена, но начальный узел не найден.",
                    error="unknown_step_no_start",
                )
            return self._resolve_node_entry(
                start_node,
                matched_button_id=None,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=normalized_message,
                trace=trace,
            )

        current_node = node_index[normalized_step]
        outgoing = edges_by_source.get(current_node.id, [])

        logger.debug(
            "FlowExecutor.processing_node | node_id={node_id} type={node_type} edges={edge_count}",
            node_id=current_node.id,
            node_type=current_node.type,
            edge_count=len(outgoing),
        )

        if current_node.type == "ai_agent":
            logger.info(
                "FlowExecutor.ai_agent | staying on node={node_id} for conversational AI",
                node_id=current_node.id,
            )
            return self._build_ai_agent_response(current_node, config, trace=trace)

        if current_node.type == "crm_action":
            return self._handle_crm_action_node(
                current_node,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=normalized_message,
                trace=trace,
            )

        if current_node.type == "condition":
            return self._handle_condition_node(
                current_node,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=normalized_message,
                trace=trace,
            )

        if current_node.type == "api_request":
            return self._handle_api_request_node(
                current_node,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=normalized_message,
                trace=trace,
            )

        buttons = current_node.data.get("buttons", []) if current_node.type == "text_message" else []

        if buttons:
            matched_button = self._match_button(buttons, normalized_message)
            if matched_button is None:
                logger.warning(
                    "FlowExecutor.button_mismatch | node_id={node_id} message={message!r} buttons={buttons}",
                    node_id=current_node.id,
                    message=normalized_message,
                    buttons=[b.get("text") for b in buttons],
                )
                response = self._build_response(current_node, matched_button_id=None)
                response["is_waiting"] = True
                response["error"] = "button_mismatch"
                response["text"] = (
                    f"{response['text']}\n\n"
                    "Пожалуйста, выберите один из предложенных вариантов."
                )
                return response

            button_id = matched_button["id"]
            logger.info(
                "FlowExecutor.button_matched | node_id={node_id} button_id={button_id} label={label!r}",
                node_id=current_node.id,
                button_id=button_id,
                label=matched_button.get("text"),
            )

            target_edge = self._find_edge_by_handle(outgoing, button_id)
            if target_edge is None:
                target_edge = self._find_edge_by_handle(outgoing, matched_button.get("text", ""))

            if target_edge is None and len(outgoing) == 1 and outgoing[0].sourceHandle is None:
                target_edge = outgoing[0]

            if target_edge is None:
                logger.error(
                    "FlowExecutor.no_edge_for_button | node_id={node_id} button_id={button_id}",
                    node_id=current_node.id,
                    button_id=button_id,
                )
                response = self._build_response(current_node, matched_button_id=button_id)
                response["is_waiting"] = True
                response["error"] = "no_edge_for_button"
                return response

            target_node = node_index.get(target_edge.target)
            if target_node is None:
                logger.error(
                    "FlowExecutor.missing_target | edge_id={edge_id} target={target}",
                    edge_id=target_edge.id,
                    target=target_edge.target,
                )
                return self._waiting_response(
                    text="Ошибка сценария: целевой узел не найден.",
                    error="missing_target_node",
                )

            logger.info(
                "FlowExecutor.transition | from={source} to={target} via={edge_id}",
                source=current_node.id,
                target=target_node.id,
                edge_id=target_edge.id,
            )
            return self._resolve_node_entry(
                target_node,
                matched_button_id=button_id,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=normalized_message,
                trace=trace,
            )

        if outgoing:
            logger.info(
                "FlowExecutor.linear_transition | from={source} edges={count}",
                source=current_node.id,
                count=len(outgoing),
            )
            return self._resolve_linear_or_stay(
                current_node,
                outgoing,
                node_index,
                normalized_message,
                config=config,
                edges_by_source=edges_by_source,
                trace=trace,
            )

        logger.info("FlowExecutor.terminal | node_id={node_id}", node_id=current_node.id)
        response = self._build_response(current_node, matched_button_id=None)
        response["is_terminal"] = True
        response["text"] = response["text"] or "Диалог завершён. Спасибо за обращение!"
        self._trace_node(trace, response["node_id"], response["node_type"], "Terminal")
        return response

    @staticmethod
    def build_bot_config(bot: Any) -> dict[str, Any]:
        schedule = bot.schedule_config if isinstance(bot.schedule_config, dict) else {}
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

    def _resolve_node_entry(
        self,
        node: Any,
        *,
        matched_button_id: str | None,
        config: dict[str, Any],
        node_index: dict[str, Any],
        edges_by_source: dict[str, list[Any]],
        incoming_message: str,
        trace: ExecutionTraceBuilder | None = None,
    ) -> dict[str, Any]:
        self._trace_node(trace, node.id, node.type, self._node_trace_label(node))
        # Trigger / entry nodes are silent passthrough — advance along the first edge.
        if node.type in {"trigger", "start", "input"}:
            outgoing = edges_by_source.get(node.id, [])
            if outgoing:
                target = node_index.get(outgoing[0].target)
                if target is not None:
                    logger.info(
                        "FlowExecutor.trigger_passthrough | from={source} to={target}",
                        source=node.id,
                        target=target.id,
                    )
                    return self._resolve_node_entry(
                        target,
                        matched_button_id=matched_button_id,
                        config=config,
                        node_index=node_index,
                        edges_by_source=edges_by_source,
                        incoming_message=incoming_message,
                        trace=trace,
                    )
        if node.type == "ai_agent":
            return self._build_ai_agent_response(node, config, trace=trace)
        if node.type == "crm_action":
            return self._handle_crm_action_node(
                node,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=incoming_message,
                trace=trace,
            )
        if node.type == "condition":
            return self._handle_condition_node(
                node,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=incoming_message,
                trace=trace,
            )
        if node.type == "api_request":
            return self._handle_api_request_node(
                node,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=incoming_message,
                trace=trace,
            )
        if node.type == "function":
            return self._handle_function_node(
                node,
                config=config,
                node_index=node_index,
                edges_by_source=edges_by_source,
                incoming_message=incoming_message,
                trace=trace,
            )
        return self._build_response(node, matched_button_id=matched_button_id)

    def _handle_crm_action_node(
        self,
        node: Any,
        *,
        config: dict[str, Any],
        node_index: dict[str, Any],
        edges_by_source: dict[str, list[Any]],
        incoming_message: str,
        trace: ExecutionTraceBuilder | None = None,
    ) -> dict[str, Any]:
        node_data = node.data or {}
        params = node_data.get("params") or {}
        target = str(node_data.get("target") or params.get("target") or "").strip().lower()

        if target == "internal":
            action_data = {
                "target": "internal",
                "action": node_data.get("action") or params.get("action"),
                "params": params,
                "node_id": node.id,
            }
        else:
            platform = str(params.get("platform") or node_data.get("action_type") or "amocrm").lower()
            if platform not in {"amocrm", "bitrix24"}:
                platform = "amocrm"
            action_data = {
                "platform": platform,
                "pipeline_id": params.get("pipeline_id"),
                "stage_id": params.get("stage_id") or params.get("status_id"),
                "status_id": params.get("stage_id") or params.get("status_id"),
                "tags": params.get("tags") or [],
                "node_id": node.id,
            }

        outgoing = edges_by_source.get(node.id, [])
        if outgoing:
            preferred_edge = next(
                (edge for edge in outgoing if edge.sourceHandle is None),
                outgoing[0],
            )
            target_node = node_index.get(preferred_edge.target)
            if target_node is not None:
                logger.info(
                    "FlowExecutor.crm_action_advance | from={source} to={target} platform={platform}",
                    source=node.id,
                    target=target_node.id,
                    platform=action_data.get("platform") or action_data.get("target"),
                )
                follow_up = self._resolve_node_entry(
                    target_node,
                    matched_button_id=None,
                    config=config,
                    node_index=node_index,
                    edges_by_source=edges_by_source,
                    incoming_message=incoming_message,
                    trace=trace,
                )
                # Internal actions are executed by flow_parser bridge — do not queue external CRM.
                if target != "internal":
                    follow_up["crm_action"] = action_data
                    follow_up["crm_action_async"] = True
                else:
                    follow_up["crm_action"] = action_data
                    follow_up["crm_action_async"] = False
                return follow_up

        response = self._build_response(node, matched_button_id=None)
        response["text"] = response["text"] or "CRM action queued."
        response["crm_action"] = action_data
        response["crm_action_async"] = target != "internal"
        return response

    def _handle_condition_node(
        self,
        node: Any,
        *,
        config: dict[str, Any],
        node_index: dict[str, Any],
        edges_by_source: dict[str, list[Any]],
        incoming_message: str,
        trace: ExecutionTraceBuilder | None = None,
    ) -> dict[str, Any]:
        node_data = node.data or {}
        matched = self._evaluate_condition(node_data, config, incoming_message)
        handle = "true" if matched else "false"

        outgoing = edges_by_source.get(node.id, [])
        branch_edge = self._find_edge_by_handle(outgoing, handle) or next(
            (edge for edge in outgoing if edge.sourceHandle == handle),
            None,
        )

        if branch_edge is not None:
            target_node = node_index.get(branch_edge.target)
            if target_node is not None:
                logger.info(
                    "FlowExecutor.condition_branch | node_id={node_id} handle={handle} target={target}",
                    node_id=node.id,
                    handle=handle,
                    target=target_node.id,
                )
                follow_up = self._resolve_node_entry(
                    target_node,
                    matched_button_id=None,
                    config=config,
                    node_index=node_index,
                    edges_by_source=edges_by_source,
                    incoming_message=incoming_message,
                    trace=trace,
                )
                follow_up["condition_result"] = matched
                follow_up["condition_handle"] = handle
                return follow_up

        response = self._build_response(node, matched_button_id=None)
        response["condition_result"] = matched
        response["condition_handle"] = handle
        response["text"] = response["text"] or "Condition evaluated without a connected branch."
        response["is_waiting"] = True
        response["error"] = "condition_branch_missing"
        return response

    def _handle_api_request_node(
        self,
        node: Any,
        *,
        config: dict[str, Any],
        node_index: dict[str, Any],
        edges_by_source: dict[str, list[Any]],
        incoming_message: str,
        trace: ExecutionTraceBuilder | None = None,
    ) -> dict[str, Any]:
        node_data = node.data or {}
        method = str(node_data.get("method") or "POST").upper()
        url = str(node_data.get("url") or "").strip()
        headers = node_data.get("headers") or {}
        body_template = str(node_data.get("body_template") or "")
        variable_name = str(node_data.get("variable_name") or "api_response")

        success = False
        response_payload: dict[str, Any] = {"status_code": None, "body": None, "error": None}

        if not url:
            response_payload["error"] = "API URL is empty."
        else:
            try:
                with httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
                    request_kwargs: dict[str, Any] = {"headers": headers}
                    if method == "POST" and body_template:
                        request_kwargs["content"] = body_template.replace(
                            "{{message}}", incoming_message
                        )
                    http_response = client.request(method, url, **request_kwargs)
                response_payload["status_code"] = http_response.status_code
                response_payload["body"] = http_response.text[:4000]
                success = 200 <= http_response.status_code < 300
            except Exception as exc:
                response_payload["error"] = str(exc)
                logger.warning(
                    "FlowExecutor.api_request_failed | node_id={node_id} error={error}",
                    node_id=node.id,
                    error=str(exc),
                )

        handle = "success" if success else "failure"
        outgoing = edges_by_source.get(node.id, [])
        branch_edge = next(
            (edge for edge in outgoing if edge.sourceHandle == handle),
            None,
        )

        if branch_edge is not None:
            target_node = node_index.get(branch_edge.target)
            if target_node is not None:
                follow_up = self._resolve_node_entry(
                    target_node,
                    matched_button_id=None,
                    config=config,
                    node_index=node_index,
                    edges_by_source=edges_by_source,
                    incoming_message=incoming_message,
                    trace=trace,
                )
                follow_up["api_request"] = {
                    "variable_name": variable_name,
                    **response_payload,
                }
                return follow_up

        response = self._build_response(node, matched_button_id=None)
        response["api_request"] = {
            "variable_name": variable_name,
            **response_payload,
        }
        response["text"] = response["text"] or "API request completed without a connected branch."
        response["is_waiting"] = True
        response["error"] = "api_request_branch_missing"
        return response

    def _evaluate_condition(
        self,
        node_data: dict[str, Any],
        config: dict[str, Any],
        incoming_message: str,
    ) -> bool:
        condition_type = str(node_data.get("condition_type") or "expression")

        if condition_type == "working_hours":
            return self._is_within_schedule(config)

        if condition_type == "customer_tag":
            tag = str(node_data.get("tag") or "").strip().lower()
            if not tag:
                return False
            client_tags = config.get("client_tags") or []
            if isinstance(client_tags, list):
                normalized_tags = [str(item).strip().lower() for item in client_tags]
                if tag in normalized_tags:
                    return True
            return tag in incoming_message.casefold()

        expression = str(node_data.get("expression") or "true").strip().lower()
        if expression in {"true", "1", "yes"}:
            return True
        if expression in {"false", "0", "no"}:
            return False
        return expression in incoming_message.casefold()

    def _handle_function_node(
        self,
        node: Any,
        *,
        config: dict[str, Any],
        node_index: dict[str, Any],
        edges_by_source: dict[str, list[Any]],
        incoming_message: str,
        trace: ExecutionTraceBuilder | None = None,
    ) -> dict[str, Any]:
        node_data = node.data or {}
        execution_context = {
            "node_id": node.id,
            "node_type": node.type,
            "node_data": node_data,
            "incoming_message": incoming_message,
            "bot_config": {
                key: config.get(key)
                for key in (
                    "prompt_instructions",
                    "llm_model_name",
                    "llm_temperature",
                    "timezone",
                )
            },
        }

        snippet = str(config.get("custom_code_snippet") or "")
        execution_result = execute_custom_code_snippet(snippet, context=execution_context)

        outgoing = edges_by_source.get(node.id, [])
        if outgoing and execution_result.get("success"):
            preferred_edge = next(
                (edge for edge in outgoing if edge.sourceHandle is None),
                outgoing[0],
            )
            target_node = node_index.get(preferred_edge.target)
            if target_node is not None:
                logger.info(
                    "FlowExecutor.function_auto_advance | from={source} to={target}",
                    source=node.id,
                    target=target_node.id,
                )
                follow_up = self._resolve_node_entry(
                    target_node,
                    matched_button_id=None,
                    config=config,
                    node_index=node_index,
                    edges_by_source=edges_by_source,
                    incoming_message=incoming_message,
                    trace=trace,
                )
                follow_up["function_execution"] = execution_result
                return follow_up

        response = self._build_response(node, matched_button_id=None)
        response["function_execution"] = execution_result
        if execution_result.get("success"):
            result_text = execution_result.get("result")
            if result_text is not None:
                response["text"] = str(result_text)
        else:
            response["text"] = (
                response["text"]
                or "Function execution failed. Operator has been notified in logs."
            )
            response["is_waiting"] = True
            response["error"] = "function_execution_failed"
            if trace is not None:
                trace.record_error("function_execution_failed")
            self._record_diagnostic(
                config,
                DiagnosticErrorType.LLM_TIMEOUT,
                str(execution_result.get("error") or "Function execution failed"),
                node_id=node.id,
            )
        return response

    @staticmethod
    def _record_diagnostic(
        config: dict[str, Any],
        error_type: DiagnosticErrorType,
        error_message: str,
        *,
        node_id: str | None = None,
    ) -> None:
        bot_id = config.get("bot_id")
        if not bot_id:
            return
        diagnostic_log_service.schedule_log(
            bot_id=bot_id,
            client_id=config.get("client_id"),
            error_type=error_type,
            error_message=error_message,
            node_id=node_id,
        )

    @staticmethod
    def _trace_node(
        trace: ExecutionTraceBuilder | None,
        node_id: str,
        node_type: str,
        label: str | None = None,
    ) -> None:
        if trace is not None:
            trace.record_node(node_id, node_type, label=label)

    @staticmethod
    def _node_trace_label(node: Any) -> str | None:
        data = node.data or {}
        if node.type == "text_message":
            preview = str(data.get("text", "")).strip()
            return preview[:80] if preview else None
        if node.type == "ai_agent":
            return str(data.get("prompt_context", "")).strip()[:80] or "AI Agent"
        return None

    def _is_within_schedule(self, config: dict[str, Any]) -> bool:
        schedule = config.get("schedule_config") or {}
        if not schedule.get("enabled"):
            return True

        windows = schedule.get("windows") or []
        if not windows:
            return True

        tz_name = schedule.get("timezone") or config.get("timezone") or "Asia/Almaty"
        try:
            now = datetime.now(ZoneInfo(tz_name))
        except Exception:
            logger.warning("FlowExecutor.invalid_timezone | tz={tz}", tz=tz_name)
            now = datetime.now(UTC)

        weekday = now.strftime("%A").lower()
        current_time = now.strftime("%H:%M")

        for window in windows:
            day = str(window.get("day", "")).lower()
            start = str(window.get("start", "00:00"))
            end = str(window.get("end", "23:59"))
            if day and day != weekday:
                continue
            if start <= current_time <= end:
                return True

        return False

    def _parse_graph(self, graph_data: dict[str, Any]) -> FlowGraphData:
        return FlowGraphData.model_validate(graph_data)

    def _is_start_state(self, step_id: str) -> bool:
        return step_id in self.START_ALIASES

    def _index_edges(self, edges: list[Any]) -> dict[str, list[Any]]:
        index: dict[str, list[Any]] = {}
        for edge in edges:
            index.setdefault(edge.source, []).append(edge)
        return index

    def _find_start_node(self, nodes: list[Any], edges: list[Any]) -> Any | None:
        targets = {edge.target for edge in edges}

        text_nodes_without_incoming = [
            node for node in nodes if node.type == "text_message" and node.id not in targets
        ]
        if text_nodes_without_incoming:
            chosen = text_nodes_without_incoming[0]
            logger.debug(
                "FlowExecutor.start_candidate | node_id={node_id} reason=text_message_no_incoming",
                node_id=chosen.id,
            )
            return chosen

        nodes_without_incoming = [node for node in nodes if node.id not in targets]
        if nodes_without_incoming:
            chosen = nodes_without_incoming[0]
            logger.debug(
                "FlowExecutor.start_candidate | node_id={node_id} reason=no_incoming_edges",
                node_id=chosen.id,
            )
            return chosen

        welcome_nodes = [
            node
            for node in nodes
            if node.id in {"welcome", "welcome_node", "root", "start"}
        ]
        if welcome_nodes:
            return welcome_nodes[0]

        return nodes[0] if nodes else None

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

    def _find_edge_by_handle(self, edges: list[Any], handle: str) -> Any | None:
        normalized = handle.casefold()
        for edge in edges:
            if edge.sourceHandle is None:
                continue
            if edge.sourceHandle.casefold() == normalized:
                return edge
        return None

    def _resolve_linear_or_stay(
        self,
        current_node: Any,
        outgoing: list[Any],
        node_index: dict[str, Any],
        incoming_message: str,
        *,
        config: dict[str, Any],
        edges_by_source: dict[str, list[Any]],
        trace: ExecutionTraceBuilder | None = None,
    ) -> dict[str, Any]:
        if not outgoing:
            response = self._build_response(current_node, matched_button_id=None)
            response["is_terminal"] = True
            return response

        preferred_edge = next((edge for edge in outgoing if edge.sourceHandle is None), outgoing[0])
        target_node = node_index.get(preferred_edge.target)

        if target_node is None:
            return self._waiting_response(
                text="Ошибка сценария: следующий шаг не найден.",
                error="linear_target_missing",
            )

        return self._resolve_node_entry(
            target_node,
            matched_button_id=None,
            config=config,
            node_index=node_index,
            edges_by_source=edges_by_source,
            incoming_message=incoming_message,
            trace=trace,
        )

    def _extract_text(self, node: Any) -> str:
        data = node.data or {}
        node_type = node.type

        if node_type == "text_message":
            return str(data.get("text", ""))
        if node_type == "ai_agent":
            return str(data.get("prompt_context", ""))
        if node_type == "condition":
            return str(data.get("expression") or data.get("tag") or "Condition")
        if node_type == "api_request":
            return str(data.get("url") or "API Request")
        if node_type == "crm_action":
            action = data.get("action_type", "crm_action")
            return f"Выполняется функция: {action}"
        return ""

    def _extract_buttons(self, node: Any) -> list[dict[str, str]]:
        if node.type != "text_message":
            return []
        buttons = node.data.get("buttons", [])
        return [{"id": str(b["id"]), "text": str(b["text"])} for b in buttons]

    def _build_ai_agent_response(
        self,
        node: Any,
        config: dict[str, Any],
        *,
        trace: ExecutionTraceBuilder | None = None,
    ) -> dict[str, Any]:
        self._trace_node(trace, node.id, node.type, self._node_trace_label(node))
        response = self._build_response(node, matched_button_id=None)
        response["requires_ai"] = True
        response["text"] = ""
        response["is_waiting"] = False
        response["is_terminal"] = False
        node_data = node.data if isinstance(node.data, dict) else {}
        response["llm_model_name"] = (
            node_data.get("model_name")
            or node_data.get("llm_model_name")
            or config.get("llm_model_name")
        )
        response["llm_temperature"] = (
            node_data.get("temperature")
            if node_data.get("temperature") is not None
            else config.get("llm_temperature")
        )
        global_prompt = str(config.get("prompt_instructions") or "").strip()
        if global_prompt:
            response["data"] = {
                **(response.get("data") or {}),
                "global_prompt_instructions": global_prompt,
            }
        return response

    def _build_response(
        self,
        node: Any,
        matched_button_id: str | None,
    ) -> dict[str, Any]:
        buttons = self._extract_buttons(node)

        return {
            "node_id": node.id,
            "node_type": node.type,
            "text": self._extract_text(node),
            "buttons": buttons,
            "data": node.data,
            "matched_button_id": matched_button_id,
            "is_waiting": False,
            "is_terminal": False,
            "error": None,
        }

    def _inactive_response(self) -> dict[str, Any]:
        return {
            "node_id": self.INACTIVE_STEP_ID,
            "node_type": "inactive",
            "text": "Бот временно отключён администратором.",
            "buttons": [],
            "data": {},
            "matched_button_id": None,
            "is_waiting": True,
            "is_terminal": False,
            "error": "bot_inactive",
            "bot_silent": True,
        }

    def _waiting_response(self, text: str, error: str) -> dict[str, Any]:
        logger.warning("FlowExecutor.waiting_state | error={error}", error=error)
        return {
            "node_id": self.WAITING_STEP_ID,
            "node_type": "waiting",
            "text": text,
            "buttons": [],
            "data": {},
            "matched_button_id": None,
            "is_waiting": True,
            "is_terminal": False,
            "error": error,
        }
