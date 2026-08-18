"""Cursor-optimized diagnostic dump builder for LLM-assisted debugging."""

from __future__ import annotations

import platform
import sys
import uuid
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.core_models import Bot, BotDiagnosticLog
from app.schemas.diagnostic_schemas import DiagnosticsExportResponse
from app.services.platform_health_service import platform_health_service


class CursorDiagnosticExporter:
    """Aggregate Error Vault rows + safe environment metadata into markdown."""

    async def export_markdown(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> DiagnosticsExportResponse:
        safe_limit = max(1, min(limit, 50))
        logs, bot_name, total = await self._load_error_logs(db, bot_id=bot_id, limit=safe_limit)
        environment = await self._collect_environment(bot_id=bot_id, bot_name=bot_name)
        metrics = self._collect_metrics(logs=logs, total=total, limit=safe_limit)
        markdown = self._render_markdown(
            environment=environment,
            logs=logs,
            metrics=metrics,
            bot_id=bot_id,
        )

        logger.info(
            "CursorDiagnostics.exported | bot_id={bot_id} errors={count}",
            bot_id=bot_id,
            count=len(logs),
        )
        return DiagnosticsExportResponse(
            markdown=markdown,
            bot_id=bot_id,
            bot_name=bot_name,
            error_count=len(logs),
            generated_at=datetime.now(UTC),
        )

    async def _load_error_logs(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID | None,
        limit: int,
    ) -> tuple[list[BotDiagnosticLog], str | None, int]:
        stmt = select(BotDiagnosticLog).options(selectinload(BotDiagnosticLog.bot))
        count_stmt = select(func.count(BotDiagnosticLog.id))
        bot_name: str | None = None

        if bot_id is not None:
            bot_result = await db.execute(select(Bot).where(Bot.id == bot_id))
            bot = bot_result.scalar_one_or_none()
            if bot is None:
                raise ValueError(f"Bot '{bot_id}' not found.")
            bot_name = bot.name
            stmt = stmt.where(BotDiagnosticLog.bot_id == bot_id)
            count_stmt = count_stmt.where(BotDiagnosticLog.bot_id == bot_id)

        total = int((await db.execute(count_stmt)).scalar_one() or 0)
        result = await db.execute(
            stmt.order_by(BotDiagnosticLog.created_at.desc()).limit(limit)
        )
        rows = list(result.scalars().all())
        return rows, bot_name, total

    async def _collect_environment(
        self,
        *,
        bot_id: uuid.UUID | None,
        bot_name: str | None,
    ) -> dict[str, str]:
        postgres = await platform_health_service.check_postgresql()
        redis_health = platform_health_service.check_redis()

        return {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "app_environment": getattr(settings, "ENVIRONMENT", "development"),
            "llm_provider": settings.LLM_PROVIDER,
            "openai_chat_model": settings.OPENAI_CHAT_MODEL,
            "postgres_status": postgres.status,
            "postgres_latency_ms": str(postgres.latency_ms if postgres.latency_ms is not None else "n/a"),
            "redis_status": redis_health.status,
            "redis_latency_ms": str(
                redis_health.latency_ms if redis_health.latency_ms is not None else "n/a"
            ),
            "llm_cache_enabled": str(bool(getattr(settings, "LLM_CACHE_ENABLED", True))).lower(),
            "llm_cache_ttl_seconds": str(getattr(settings, "LLM_CACHE_TTL_SECONDS", 86400)),
            "bot_id": str(bot_id) if bot_id else "all",
            "bot_name": bot_name or "workspace",
        }

    def _collect_metrics(
        self,
        *,
        logs: list[BotDiagnosticLog],
        total: int,
        limit: int,
    ) -> dict[str, str | int]:
        by_type: dict[str, int] = {}
        for row in logs:
            key = row.error_type.value if hasattr(row.error_type, "value") else str(row.error_type)
            by_type[key] = by_type.get(key, 0) + 1

        return {
            "exported_rows": len(logs),
            "export_limit": limit,
            "total_matching_rows": total,
            "error_type_breakdown": ", ".join(
                f"{name}={count}" for name, count in sorted(by_type.items())
            )
            or "none",
        }

    def _render_markdown(
        self,
        *,
        environment: dict[str, str],
        logs: list[BotDiagnosticLog],
        metrics: dict[str, str | int],
        bot_id: uuid.UUID | None,
    ) -> str:
        lines: list[str] = [
            "# MP.AI Cursor Diagnostic Dump",
            "",
            "Paste this block into Cursor Composer to reproduce and fix platform errors.",
            "",
            "### ENVIRONMENT",
            "",
            f"- **generated_at_utc**: `{environment['generated_at_utc']}`",
            f"- **python_version**: `{environment['python_version']}`",
            f"- **platform**: `{environment['platform']}`",
            f"- **app_environment**: `{environment['app_environment']}`",
            f"- **bot_id**: `{environment['bot_id']}`",
            f"- **bot_name**: `{environment['bot_name']}`",
            f"- **postgres**: `{environment['postgres_status']}` (latency_ms={environment['postgres_latency_ms']})",
            f"- **redis**: `{environment['redis_status']}` (latency_ms={environment['redis_latency_ms']})",
            f"- **llm_provider**: `{environment['llm_provider']}`",
            f"- **openai_chat_model**: `{environment['openai_chat_model']}`",
            f"- **llm_cache_enabled**: `{environment['llm_cache_enabled']}`",
            f"- **llm_cache_ttl_seconds**: `{environment['llm_cache_ttl_seconds']}`",
            "",
            "### METRICS",
            "",
            f"- **exported_rows**: `{metrics['exported_rows']}` / limit `{metrics['export_limit']}`",
            f"- **total_matching_rows**: `{metrics['total_matching_rows']}`",
            f"- **error_type_breakdown**: `{metrics['error_type_breakdown']}`",
            f"- **scope**: `{'bot' if bot_id else 'workspace'}`",
            "",
            "### ERROR_LOGS",
            "",
        ]

        if not logs:
            lines.append("_No diagnostic errors found for this context._")
            lines.append("")
        else:
            for index, row in enumerate(logs, start=1):
                error_type = (
                    row.error_type.value if hasattr(row.error_type, "value") else str(row.error_type)
                )
                created = row.created_at.isoformat() if row.created_at else "unknown"
                bot_label = ""
                if getattr(row, "bot", None) is not None:
                    bot_label = getattr(row.bot, "name", "") or ""
                lines.extend(
                    [
                        f"#### {index}. `{error_type}` — {created}",
                        "",
                        f"- **log_id**: `{row.id}`",
                        f"- **bot_id**: `{row.bot_id}`",
                        f"- **bot_name**: `{bot_label or 'n/a'}`",
                        f"- **client_id**: `{row.client_id or 'n/a'}`",
                        f"- **node_id**: `{row.node_id or 'n/a'}`",
                        "",
                        "```text",
                        row.error_message.strip() or "(empty message)",
                        "```",
                        "",
                    ]
                )

        lines.extend(
            [
                "### INSTRUCTIONS_FOR_CURSOR",
                "",
                "1. Identify the root cause from ERROR_LOGS + ENVIRONMENT health.",
                "2. Propose a minimal patch in the MP.AI backend/frontend monorepo.",
                "3. Prefer fixing orchestrator, webhook, CRM, or billing paths without broad refactors.",
                "",
            ]
        )
        return "\n".join(lines)


cursor_diagnostic_exporter = CursorDiagnosticExporter()
