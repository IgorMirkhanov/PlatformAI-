"""Celery tasks for asynchronous AI / bot response generation."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery.exceptions import MaxRetriesExceededError
from loguru import logger

from app.core.celery_app import celery_app
from app.services.llm.types import (
    SAFE_USER_FALLBACK_MESSAGE,
    TransientLLMError,
    format_execution_failure_message,
)


def _is_transient_provider_error(exc: BaseException) -> bool:
    if isinstance(exc, TransientLLMError):
        return True
    try:
        from openai import APIConnectionError, APITimeoutError, RateLimitError

        if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)):
            return True
    except ImportError:  # pragma: no cover
        pass
    return False


async def _generate_ai_response_async(
    *,
    bot_id: str,
    client_id: str,
    incoming_message: str,
    current_node_data: dict[str, Any],
    node_id: str | None,
    channel: str | None,
) -> dict[str, Any]:
    from app.core.database import async_session_factory
    from app.services.ai_orchestrator import AIOrchestrator

    orchestrator = AIOrchestrator()
    async with async_session_factory() as db:
        result = await orchestrator.generate_ai_response(
            client_id=uuid.UUID(client_id),
            current_node_data=current_node_data or {},
            incoming_message=incoming_message,
            db_session=db,
            bot_id=uuid.UUID(bot_id),
            node_id=node_id,
            channel=channel,
            propagate_transient=True,
        )
        await db.commit()

    text = result if isinstance(result, str) else result.text
    media = [] if isinstance(result, str) else list(result.media_attachments or [])
    return {
        "ok": True,
        "bot_id": bot_id,
        "client_id": client_id,
        "text": text,
        "media_attachments": [
            attachment.model_dump() if hasattr(attachment, "model_dump") else attachment
            for attachment in media
        ],
        "degraded": False,
    }


async def _log_exhausted_failure(
    *,
    bot_id: str,
    client_id: str | None,
    node_id: str | None,
    error: str,
    primary_model: str | None,
    fallback_model: str | None,
) -> None:
    from app.services.llm_orchestrator import llm_orchestrator

    message = format_execution_failure_message(
        provider_error=error,
        primary_model=primary_model,
        fallback_model=fallback_model,
        extras={"retries_exhausted": True},
    )
    try:
        await llm_orchestrator.record_execution_failure(
            bot_id=uuid.UUID(bot_id),
            client_id=uuid.UUID(client_id) if client_id else None,
            node_id=node_id,
            message=message,
            db=None,
        )
    except Exception:
        logger.exception("BotTasks.diagnostic_log_failed | bot_id={bot_id}", bot_id=bot_id)


@celery_app.task(
    name="app.tasks.bot_tasks.generate_ai_response",
    bind=True,
    max_retries=3,
    default_retry_delay=2,
)
def generate_ai_response(
    self,
    bot_id: str,
    client_id: str,
    incoming_message: str,
    current_node_data: dict[str, Any] | None = None,
    node_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """
    Generate an AI reply asynchronously.

    Transient provider errors (``APITimeoutError``, ``APIConnectionError``,
    ``RateLimitError``, ``TransientLLMError``) trigger exponential backoff:
    ``countdown = 2 ** retries`` with ``max_retries=3``.
    """
    from app.core.config import settings

    primary = getattr(settings, "OPENAI_CHAT_MODEL", "gpt-4o")
    fallback = getattr(settings, "OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
    node_model = None
    if isinstance(current_node_data, dict):
        node_model = current_node_data.get("llm_model_name") or current_node_data.get("model")

    logger.info(
        "BotTasks.generate_ai_response_start | task_id={task_id} bot_id={bot_id} "
        "client_id={client_id} retries={retries} model={model}",
        task_id=self.request.id,
        bot_id=bot_id,
        client_id=client_id,
        retries=self.request.retries,
        model=node_model or primary,
    )

    try:
        result = asyncio.run(
            _generate_ai_response_async(
                bot_id=bot_id,
                client_id=client_id,
                incoming_message=incoming_message,
                current_node_data=current_node_data or {},
                node_id=node_id,
                channel=channel,
            )
        )
        logger.info(
            "BotTasks.generate_ai_response_complete | task_id={task_id} bot_id={bot_id}",
            task_id=self.request.id,
            bot_id=bot_id,
        )
        return result
    except Exception as exc:
        if _is_transient_provider_error(exc):
            countdown = 2 ** self.request.retries
            logger.warning(
                "BotTasks.generate_ai_response_retry | task_id={task_id} bot_id={bot_id} "
                "countdown={countdown} retries={retries} error={error}",
                task_id=self.request.id,
                bot_id=bot_id,
                countdown=countdown,
                retries=self.request.retries,
                error=str(exc),
            )
            try:
                raise self.retry(exc=exc, countdown=countdown, max_retries=3)
            except MaxRetriesExceededError:
                asyncio.run(
                    _log_exhausted_failure(
                        bot_id=bot_id,
                        client_id=client_id,
                        node_id=node_id,
                        error=str(exc),
                        primary_model=str(node_model or primary),
                        fallback_model=str(fallback),
                    )
                )
                return {
                    "ok": False,
                    "degraded": True,
                    "bot_id": bot_id,
                    "client_id": client_id,
                    "text": SAFE_USER_FALLBACK_MESSAGE,
                    "media_attachments": [],
                    "error": str(exc)[:500],
                }

        logger.exception(
            "BotTasks.generate_ai_response_failed | task_id={task_id} bot_id={bot_id} error={error}",
            task_id=self.request.id,
            bot_id=bot_id,
            error=str(exc),
        )
        asyncio.run(
            _log_exhausted_failure(
                bot_id=bot_id,
                client_id=client_id,
                node_id=node_id,
                error=str(exc),
                primary_model=str(node_model or primary),
                fallback_model=str(fallback),
            )
        )
        return {
            "ok": False,
            "degraded": True,
            "bot_id": bot_id,
            "client_id": client_id,
            "text": SAFE_USER_FALLBACK_MESSAGE,
            "media_attachments": [],
            "error": str(exc)[:500],
        }


def enqueue_generate_ai_response(
    *,
    bot_id: uuid.UUID | str,
    client_id: uuid.UUID | str,
    incoming_message: str,
    current_node_data: dict[str, Any] | None = None,
    node_id: str | None = None,
    channel: str | None = None,
) -> str:
    """Helper for API / webhook handlers — returns Celery task id."""
    async_result = generate_ai_response.delay(
        str(bot_id),
        str(client_id),
        incoming_message,
        current_node_data or {},
        node_id,
        channel,
    )
    return str(async_result.id)
