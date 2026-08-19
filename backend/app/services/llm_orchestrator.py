"""LLM orchestration — timeouts, primary→fallback chain, graceful degradation."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core_models import DiagnosticErrorType
from app.services.diagnostic_log_service import diagnostic_log_service
from app.services.llm.client import OpenAIChatClient
from app.services.llm.types import (
    SAFE_USER_FALLBACK_MESSAGE,
    LLMCompletion,
    TransientLLMError,
    format_execution_failure_message,
)


class LLMOrchestrator:
    """
    Execute chat completions with a strict client timeout and one-shot fallback.

    Primary model (node selection or ``OPENAI_CHAT_MODEL``, default gpt-4o) →
    on 429 / 5xx / timeout → retry once on ``OPENAI_FALLBACK_MODEL`` (gpt-4o-mini).
    """

    SAFE_FALLBACK_MESSAGE = SAFE_USER_FALLBACK_MESSAGE

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 20.0)
        )
        self.fallback_model = (
            fallback_model
            or getattr(settings, "OPENAI_FALLBACK_MODEL", None)
            or "gpt-4o-mini"
        )
        self._client = OpenAIChatClient(timeout_seconds=self.timeout_seconds)

    def resolve_primary_model(self, model_name: str | None = None) -> str:
        return (model_name or settings.OPENAI_CHAT_MODEL or "gpt-4o").strip() or "gpt-4o"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.4,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
        db: AsyncSession | None = None,
        tools: list[dict[str, Any]] | None = None,
        degrade_on_exhaustion: bool = False,
    ) -> LLMCompletion:
        """
        Run primary then optional fallback on transient provider failures only.

        When ``degrade_on_exhaustion`` is True, logs ``LLM_EXECUTION_FAILURE`` and
        returns a safe user-facing message instead of raising.
        """
        primary = self.resolve_primary_model(model)
        fallback = self.fallback_model

        try:
            result = await self._client.chat_completion(
                messages=messages,
                model=primary,
                temperature=temperature,
                tools=tools,
            )
            result = await self._resolve_tool_calls(
                result,
                messages=messages,
                model=primary,
                temperature=temperature,
                tools=tools,
                bot_id=bot_id,
                client_id=client_id,
                db=db,
            )
            result.primary_model = primary
            result.fallback_model = fallback
            result.used_fallback = False
            return result
        except TransientLLMError as primary_exc:
            logger.warning(
                "LLMOrchestrator.primary_failed | model={model} kind={kind} status={status} error={error}",
                model=primary,
                kind=primary_exc.kind.value,
                status=primary_exc.status_code,
                error=str(primary_exc),
            )
            if not fallback or fallback == primary:
                return await self._handle_exhaustion(
                    primary_exc,
                    primary_model=primary,
                    fallback_model=fallback,
                    bot_id=bot_id,
                    client_id=client_id,
                    node_id=node_id,
                    db=db,
                    degrade_on_exhaustion=degrade_on_exhaustion,
                )
            try:
                result = await self._client.chat_completion(
                    messages=messages,
                    model=fallback,
                    temperature=temperature,
                    tools=tools,
                )
                result = await self._resolve_tool_calls(
                    result,
                    messages=messages,
                    model=fallback,
                    temperature=temperature,
                    tools=tools,
                    bot_id=bot_id,
                    client_id=client_id,
                    db=db,
                )
                result.primary_model = primary
                result.fallback_model = fallback
                result.used_fallback = True
                logger.info(
                    "LLMOrchestrator.fallback_success | primary={primary} fallback={fallback}",
                    primary=primary,
                    fallback=fallback,
                )
                return result
            except Exception as fallback_exc:
                logger.error(
                    "LLMOrchestrator.fallback_failed | primary={primary} fallback={fallback} error={error}",
                    primary=primary,
                    fallback=fallback,
                    error=str(fallback_exc),
                )
                return await self._handle_exhaustion(
                    fallback_exc,
                    primary_model=primary,
                    fallback_model=fallback,
                    bot_id=bot_id,
                    client_id=client_id,
                    node_id=node_id,
                    db=db,
                    degrade_on_exhaustion=degrade_on_exhaustion,
                )

    async def _resolve_tool_calls(
        self,
        result: LLMCompletion,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        tools: list[dict[str, Any]] | None,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        db: AsyncSession | None,
    ) -> LLMCompletion:
        """Run one tool round-trip when the model returns function calls."""
        if not result.tool_calls or db is None or bot_id is None:
            return result

        from app.models.core_models import Bot, Client
        from app.services.llm.tool_executor import execute_tool_call

        bot = await db.get(Bot, bot_id)
        if bot is None:
            return result
        client: Client | None = None
        if client_id is not None:
            client = await db.get(Client, client_id)

        channel = "web"
        channel_user_id: str | None = None
        if client is not None:
            channel_user_id = client.external_id
            source = str(getattr(client, "source", "") or "").lower()
            if "telegram" in source:
                channel = "telegram"
            elif "whatsapp" in source or "wazzup" in source:
                channel = "whatsapp"
            elif "web" in source or "widget" in source:
                channel = "web"

        follow_up = list(messages)
        follow_up.append(
            {
                "role": "assistant",
                "content": result.text or None,
                "tool_calls": [
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {
                            "name": tc.get("name"),
                            "arguments": tc.get("arguments"),
                        },
                    }
                    for tc in result.tool_calls
                ],
            }
        )

        for tc in result.tool_calls:
            tool_result = await execute_tool_call(
                db,
                bot=bot,
                client=client,
                tool_name=str(tc.get("name") or ""),
                arguments_json=str(tc.get("arguments") or "{}"),
                channel=channel,
                channel_user_id=channel_user_id,
            )
            import json as _json

            follow_up.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": _json.dumps(tool_result, ensure_ascii=False),
                }
            )

        # Second completion — model reads tool output and replies to the user.
        final = await self._client.chat_completion(
            messages=follow_up,
            model=model,
            temperature=temperature,
            tools=tools,
        )
        final.tool_calls = None
        return final

    async def _handle_exhaustion(
        self,
        exc: BaseException,
        *,
        primary_model: str,
        fallback_model: str,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        node_id: str | None,
        db: AsyncSession | None,
        degrade_on_exhaustion: bool,
    ) -> LLMCompletion:
        message = format_execution_failure_message(
            provider_error=str(exc),
            primary_model=primary_model,
            fallback_model=fallback_model,
        )
        # Only persist diagnostics when we are done retrying (graceful degrade path).
        # Celery callers keep ``degrade_on_exhaustion=False`` so they can retry first.
        if degrade_on_exhaustion:
            await self.record_execution_failure(
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                message=message,
                db=db,
            )
            return LLMCompletion(
                text=self.SAFE_FALLBACK_MESSAGE,
                model=fallback_model or primary_model,
                primary_model=primary_model,
                fallback_model=fallback_model,
                used_fallback=True,
            )
        if isinstance(exc, TransientLLMError):
            raise exc
        raise TransientLLMError(str(exc), model=primary_model, cause=exc) from exc

    async def record_execution_failure(
        self,
        *,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        node_id: str | None,
        message: str,
        db: AsyncSession | None = None,
    ) -> None:
        if bot_id is None:
            logger.error("LLMOrchestrator.execution_failure | {message}", message=message)
            return

        error_type = DiagnosticErrorType.LLM_EXECUTION_FAILURE
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
        except Exception as log_exc:
            logger.exception(
                "LLMOrchestrator.diagnostic_log_failed | error={error}",
                error=str(log_exc),
            )


llm_orchestrator = LLMOrchestrator()
