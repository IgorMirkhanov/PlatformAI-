"""Bot lifecycle: cascading delete and clone/duplication."""

from __future__ import annotations

import copy
import shutil
import uuid
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.flow_cache import published_flow_cache
from app.core.llm_cache import llm_response_cache
from app.core.rag_cache import rag_activation_cache
from app.core.vector_db import purge_bot_vectors
from app.models.core_models import Bot, BotDiagnosticLog, BotFlow, KnowledgeBaseDocument
from app.models.flow import Flow
from app.models.usage import LLMUsageLog
from app.schemas.core_schemas import CreateBotResponse


class BotNotFoundError(LookupError):
    """Raised when the target bot is missing or soft-deleted."""


class BotOrgMismatchError(PermissionError):
    """Raised when the bot does not belong to the expected organization."""


class BotService:
    """Safe bot CRUD helpers for hard-delete cascade and cloning."""

    async def delete_bot_cascade(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID | int | str,
        org_id: uuid.UUID | int | str,
    ) -> dict[str, Any]:
        """
        Permanently delete a bot and all associated tenant data.

        Order of operations:
        1. Load + authorize (org match)
        2. Stop WhatsApp session (best-effort, outside DB)
        3. Purge Chroma embeddings for this bot
        4. DB transaction: usage logs, diagnostics, KB docs, flows, bot row
        5. Local avatar / upload directory cleanup

        All SQL mutations happen on ``db`` so FastAPI ``get_db`` rolls back
        if any step raises before commit.
        """
        bot_uuid = self._as_uuid(bot_id, field="bot_id")
        org_uuid = self._as_uuid(org_id, field="org_id")

        bot = await self._load_bot_for_org(db, bot_uuid, org_uuid, for_delete=True)
        document_ids = [str(doc.id) for doc in (bot.knowledge_documents or [])]

        # External side effects first — failure here aborts before SQL deletes.
        await self._stop_whatsapp_session(bot_uuid)
        await purge_bot_vectors(
            str(bot_uuid),
            organization_id=str(org_uuid) if org_uuid else None,
            document_ids=document_ids,
        )

        # Explicit child cleanup (also covered by ORM/DB cascades for safety).
        await db.execute(delete(LLMUsageLog).where(LLMUsageLog.bot_id == bot_uuid))
        await db.execute(
            delete(BotDiagnosticLog).where(BotDiagnosticLog.bot_id == bot_uuid)
        )
        await db.execute(
            delete(KnowledgeBaseDocument).where(KnowledgeBaseDocument.bot_id == bot_uuid)
        )
        await db.execute(delete(BotFlow).where(BotFlow.bot_id == bot_uuid))
        await db.execute(delete(Flow).where(Flow.bot_id == bot_uuid))

        # Hard-delete the bot row; remaining children (clients, channels, …)
        # rely on PostgreSQL ON DELETE CASCADE.
        await db.execute(delete(Bot).where(Bot.id == bot_uuid))
        await db.flush()

        published_flow_cache.invalidate(bot_uuid)
        try:
            await llm_response_cache.invalidate_bot_cache(bot_uuid)
        except Exception:
            pass
        try:
            rag_activation_cache.invalidate(bot_uuid)
        except Exception:
            pass

        self._cleanup_bot_upload_dir(bot_uuid)

        logger.info(
            "BotService.delete_cascade | bot_id={bot_id} org_id={org_id} docs={docs}",
            bot_id=bot_uuid,
            org_id=org_uuid,
            docs=len(document_ids),
        )
        return {
            "bot_id": str(bot_uuid),
            "organization_id": str(org_uuid),
            "deleted": True,
            "knowledge_documents_removed": len(document_ids),
        }

    async def clone_bot(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID | int | str,
        *,
        org_id: uuid.UUID | int | str | None = None,
        current_user_id: uuid.UUID | None = None,
    ) -> CreateBotResponse:
        """
        Duplicate a bot with flow graph + prompt/LLM settings.

        The clone is inactive, has empty credentials, and is named
        ``"{Original Name} (Копия)"``. Knowledge base / channels are not copied.
        """
        source_uuid = self._as_uuid(bot_id, field="bot_id")
        org_uuid = self._as_uuid(org_id, field="org_id") if org_id is not None else None

        source = await self._load_bot_for_org(
            db,
            source_uuid,
            org_uuid,
            for_delete=False,
            require_org=org_uuid is not None,
        )
        organization_id = source.organization_id
        if organization_id is None:
            raise BotOrgMismatchError("Source bot has no organization.")

        from app.services.quota_service import QuotaExceeded, quota_service

        try:
            await quota_service.assert_can_create_bot(db, organization_id)
        except QuotaExceeded as exc:
            quota_service.raise_http(exc)

        clone_name = f"{source.name} (Копия)"
        if len(clone_name) > 255:
            clone_name = clone_name[:252] + "…"

        owner_id = current_user_id or source.user_id
        from app.services.bot_billing_service import apply_auto_trial

        clone = Bot(
            user_id=owner_id,
            organization_id=organization_id,
            project_id=source.project_id,
            name=clone_name,
            platform_type=source.platform_type,
            is_active=False,
            credentials={},
            default_chat_state=source.default_chat_state,
            timezone=source.timezone,
            schedule_config=copy.deepcopy(source.schedule_config or {}),
            prompt_instructions=source.prompt_instructions or "",
            llm_model_name=source.llm_model_name,
            llm_temperature=source.llm_temperature,
            message_split=source.message_split,
            message_buffer_delay=source.message_buffer_delay,
            custom_code_snippet=source.custom_code_snippet or "",
            created_by_id=owner_id,
            subscription_active=True,
            subscription_expires_at=None,
        )
        apply_auto_trial(clone)
        db.add(clone)
        await db.flush()

        # Prefer latest BotFlow; fall back to builder Flow.graph_snapshot.
        graph_data, nodes, edges, flow_title = await self._extract_flow_graph(db, source)

        flow = BotFlow(
            bot_id=clone.id,
            title=f"{flow_title} (копия)" if flow_title else "Draft flow (копия)",
            graph_data=graph_data,
            nodes=nodes,
            edges=edges,
            is_published=False,
        )
        db.add(flow)
        await db.flush()

        published_flow_cache.invalidate(clone.id)

        logger.info(
            "BotService.cloned | source={source} clone={clone} org={org}",
            source=source_uuid,
            clone=clone.id,
            org=organization_id,
        )

        return CreateBotResponse(
            bot_id=clone.id,
            name=clone.name,
            platform_type=clone.platform_type,
            is_active=clone.is_active,
            message="Bot cloned successfully.",
        )

    async def _extract_flow_graph(
        self,
        db: AsyncSession,
        source: Bot,
    ) -> tuple[dict[str, Any], list[Any], list[Any], str]:
        flow_result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == source.id, BotFlow.deleted_at.is_(None))
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        bot_flow = flow_result.scalar_one_or_none()
        if bot_flow is not None:
            graph = copy.deepcopy(bot_flow.graph_data or {})
            nodes = copy.deepcopy(bot_flow.nodes or graph.get("nodes") or [])
            edges = copy.deepcopy(bot_flow.edges or graph.get("edges") or [])
            if not graph:
                graph = {"nodes": nodes, "edges": edges}
            else:
                graph.setdefault("nodes", nodes)
                graph.setdefault("edges", edges)
            return graph, list(nodes), list(edges), bot_flow.title or "Draft flow"

        builder_result = await db.execute(
            select(Flow)
            .where(Flow.bot_id == source.id)
            .order_by(Flow.updated_at.desc())
            .limit(1)
        )
        builder = builder_result.scalar_one_or_none()
        if builder is not None:
            snapshot = copy.deepcopy(builder.graph_snapshot or {})
            nodes = list(snapshot.get("nodes") or [])
            edges = list(snapshot.get("edges") or [])
            return snapshot, nodes, edges, builder.name or "Draft flow"

        return {"nodes": [], "edges": []}, [], [], "Draft flow"

    async def _load_bot_for_org(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        org_id: uuid.UUID | None,
        *,
        for_delete: bool,
        require_org: bool = True,
    ) -> Bot:
        stmt = (
            select(Bot)
            .where(Bot.id == bot_id, Bot.deleted_at.is_(None))
            .options(selectinload(Bot.knowledge_documents))
        )
        result = await db.execute(stmt)
        bot = result.scalar_one_or_none()
        if bot is None:
            raise BotNotFoundError(f"Bot '{bot_id}' not found")

        if require_org:
            if org_id is None:
                raise BotOrgMismatchError("Organization id is required.")
            if bot.organization_id is not None and bot.organization_id != org_id:
                raise BotOrgMismatchError(
                    f"Bot '{bot_id}' does not belong to organization '{org_id}'"
                )
            # Allow legacy bots with null organization_id only when caller matches owner org.
            if bot.organization_id is None and for_delete:
                bot.organization_id = org_id
        return bot

    async def _stop_whatsapp_session(self, bot_id: uuid.UUID) -> None:
        try:
            from app.services.whatsapp_qr_service import whatsapp_qr_service

            await whatsapp_qr_service.stop_session(bot_id)
        except Exception as exc:
            logger.warning(
                "BotService.whatsapp_stop_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )

    def _cleanup_bot_upload_dir(self, bot_id: uuid.UUID) -> None:
        upload_root = Path(settings.UPLOADS_DIR) / "bots" / str(bot_id)
        try:
            if upload_root.exists():
                shutil.rmtree(upload_root, ignore_errors=True)
        except Exception as exc:
            logger.warning(
                "BotService.upload_cleanup_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )

    @staticmethod
    def _as_uuid(value: uuid.UUID | int | str, *, field: str) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid {field}: {value!r}") from exc


bot_service = BotService()
