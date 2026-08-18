from __future__ import annotations

import asyncio
import uuid

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.core_models import Bot, BotDiagnosticLog, DiagnosticErrorType
from app.schemas.diagnostic_schemas import DiagnosticLogListResponse, DiagnosticLogRead


class DiagnosticLogService:
    """Persists and queries AI Error Vault records without blocking runtime paths."""

    async def log(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        error_type: DiagnosticErrorType,
        error_message: str,
        client_id: uuid.UUID | None = None,
        node_id: str | None = None,
    ) -> BotDiagnosticLog:
        entry = BotDiagnosticLog(
            bot_id=bot_id,
            client_id=client_id,
            error_type=error_type,
            error_message=error_message[:4000],
            node_id=(node_id or None),
        )
        db.add(entry)
        await db.flush()
        logger.warning(
            "DiagnosticLog.recorded | bot_id={bot_id} type={error_type} node_id={node_id}",
            bot_id=bot_id,
            error_type=error_type.value,
            node_id=node_id,
        )
        return entry

    def schedule_log(
        self,
        *,
        bot_id: uuid.UUID | str,
        error_type: DiagnosticErrorType,
        error_message: str,
        client_id: uuid.UUID | str | None = None,
        node_id: str | None = None,
    ) -> None:
        """Fire-and-forget write for sync execution paths (flow executor)."""
        try:
            resolved_bot_id = bot_id if isinstance(bot_id, uuid.UUID) else uuid.UUID(str(bot_id))
        except ValueError:
            logger.error("DiagnosticLog.invalid_bot_id | bot_id={bot_id}", bot_id=bot_id)
            return

        resolved_client_id: uuid.UUID | None = None
        if client_id is not None:
            try:
                resolved_client_id = (
                    client_id if isinstance(client_id, uuid.UUID) else uuid.UUID(str(client_id))
                )
            except ValueError:
                resolved_client_id = None

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._persist_background(
                    bot_id=resolved_bot_id,
                    client_id=resolved_client_id,
                    error_type=error_type,
                    error_message=error_message,
                    node_id=node_id,
                )
            )
        except RuntimeError:
            logger.debug("DiagnosticLog.no_event_loop | skipping async write")

    async def _persist_background(
        self,
        *,
        bot_id: uuid.UUID,
        error_type: DiagnosticErrorType,
        error_message: str,
        client_id: uuid.UUID | None,
        node_id: str | None,
    ) -> None:
        async with async_session_factory() as db:
            try:
                await self.log(
                    db,
                    bot_id=bot_id,
                    client_id=client_id,
                    error_type=error_type,
                    error_message=error_message,
                    node_id=node_id,
                )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.exception(
                    "DiagnosticLog.persist_failed | bot_id={bot_id} error={error}",
                    bot_id=bot_id,
                    error=str(exc),
                )

    async def list_recent_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        limit: int = 25,
    ) -> DiagnosticLogListResponse:
        safe_limit = max(1, min(limit, 100))
        bots_result = await db.execute(select(Bot.id, Bot.name).where(Bot.user_id == user_id))
        bot_rows = bots_result.all()
        if not bot_rows:
            return DiagnosticLogListResponse(logs=[], total=0)

        bot_ids = [row[0] for row in bot_rows]
        bot_names = {row[0]: row[1] for row in bot_rows}

        total_result = await db.execute(
            select(func.count(BotDiagnosticLog.id)).where(BotDiagnosticLog.bot_id.in_(bot_ids))
        )
        total = int(total_result.scalar_one() or 0)

        logs_result = await db.execute(
            select(BotDiagnosticLog)
            .where(BotDiagnosticLog.bot_id.in_(bot_ids))
            .order_by(BotDiagnosticLog.created_at.desc())
            .limit(safe_limit)
        )
        rows = logs_result.scalars().all()

        return DiagnosticLogListResponse(
            logs=[
                DiagnosticLogRead(
                    id=row.id,
                    bot_id=row.bot_id,
                    bot_name=bot_names.get(row.bot_id, ""),
                    client_id=row.client_id,
                    error_type=row.error_type,
                    error_message=row.error_message,
                    node_id=row.node_id,
                    created_at=row.created_at,
                )
                for row in rows
            ],
            total=total,
        )

    @staticmethod
    def classify_llm_failure_code(exc: Exception) -> str:
        """Stable console/ops code for Telegram LLM failures."""
        from app.services.llm.base import (
            InsufficientCreditsForLLMError,
            LLMAuthenticationError,
            LLMRateLimitError,
            LLMTimeoutError,
        )

        if isinstance(exc, LLMAuthenticationError):
            return "INVALID_API_KEY"
        if isinstance(exc, InsufficientCreditsForLLMError):
            return "INSUFFICIENT_FUNDS"
        if isinstance(exc, LLMRateLimitError):
            message = str(exc).lower()
            if any(token in message for token in ("quota", "insufficient_quota", "billing")):
                return "LLM_QUOTA_EXCEEDED"
            return "LLM_RATE_LIMIT"
        if isinstance(exc, LLMTimeoutError):
            return "LLM_TIMEOUT"

        message = str(exc).lower()
        if any(
            token in message
            for token in (
                "invalid api key",
                "incorrect api key",
                "invalid_api_key",
                "authentication",
                "unauthorized",
                "401",
                "403",
            )
        ):
            return "INVALID_API_KEY"
        if any(
            token in message
            for token in (
                "quota",
                "insufficient_quota",
                "billing",
                "credit",
                "balance",
                "funds",
            )
        ):
            if "insufficient" in message or "quota" in message or "credit" in message:
                return "LLM_QUOTA_EXCEEDED"
        if any(token in message for token in ("timeout", "timed out", "deadline")):
            return "LLM_TIMEOUT"
        if any(token in message for token in ("429", "rate limit")):
            return "LLM_RATE_LIMIT"
        return "LLM_EXECUTION_FAILURE"

    @staticmethod
    def classify_llm_error(exc: Exception) -> DiagnosticErrorType:
        code = DiagnosticLogService.classify_llm_failure_code(exc)
        if code in {"INSUFFICIENT_FUNDS", "LLM_QUOTA_EXCEEDED"}:
            return DiagnosticErrorType.INSUFFICIENT_FUNDS
        if code == "LLM_TIMEOUT":
            return DiagnosticErrorType.LLM_TIMEOUT
        if code == "INVALID_API_KEY":
            return DiagnosticErrorType.LLM_EXECUTION_FAILURE
        return DiagnosticErrorType.LLM_EXECUTION_FAILURE

diagnostic_log_service = DiagnosticLogService()
