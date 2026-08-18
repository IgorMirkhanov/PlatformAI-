"""Async knowledge-base ingestion with explicit lifecycle statuses."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot, KnowledgeBaseDocument, KnowledgeDocumentStatus
from app.services.knowledge_base_service import knowledge_base_service


_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md", ".markdown", ".csv", ".json"}


class KnowledgeIngestionService:
    """Create PENDING rows and drive PARSING → INDEXED / FAILED via Celery."""

    @staticmethod
    def _format_from_name(file_name: str) -> str | None:
        if "." not in file_name:
            return None
        return file_name[file_name.rfind(".") + 1 :].lower() or None

    async def create_pending_document(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        file_name: str,
        source_type: str = "file",
        format_hint: str | None = None,
    ) -> KnowledgeBaseDocument:
        bot = await knowledge_base_service._get_bot(db, bot_id)
        normalized = (file_name or "document").strip() or "document"
        document = KnowledgeBaseDocument(
            bot_id=bot.id,
            file_name=normalized,
            source_type=source_type if source_type in {"file", "text", "web", "google_drive"} else "file",
            format=format_hint or self._format_from_name(normalized),
            character_count=0,
            chunk_count=0,
            is_context_active=True,
            status=KnowledgeDocumentStatus.PENDING,
            progress=0,
            error_message=None,
        )
        db.add(document)
        await db.flush()
        logger.info(
            "RAG.pending_created | bot_id={bot_id} document_id={document_id} file={file}",
            bot_id=bot.id,
            document_id=document.id,
            file=normalized,
        )
        return document

    async def enqueue_file_ingest(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist PENDING row then enqueue Celery ingest. Returns task + document ids."""
        extension = filename[filename.rfind(".") :].lower() if "." in filename else ""
        if extension and extension not in _SUPPORTED_EXTENSIONS:
            raise ValueError("Supported formats: PDF, TXT, DOCX, MD, CSV, JSON.")

        bot = await knowledge_base_service._get_bot(db, bot_id)
        document = await self.create_pending_document(
            db,
            bot_id,
            file_name=filename,
            source_type="file",
        )
        await db.commit()

        from app.tasks.rag_tasks import enqueue_document_ingest

        org_id = str(bot.organization_id) if bot.organization_id else None
        task_id = enqueue_document_ingest(
            bot_id=bot_id,
            document_id=document.id,
            filename=filename,
            content=content,
            content_type=content_type,
            source_type="file",
            organization_id=org_id,
            metadata=metadata,
        )
        return {
            "task_id": task_id,
            "document_id": str(document.id),
            "bot_id": str(bot_id),
            "kb_id": str(bot_id),
            "status": KnowledgeDocumentStatus.PENDING.value,
        }

    async def enqueue_url_ingest(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        url: str,
        file_name: str | None = None,
        crawl_depth: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bot = await knowledge_base_service._get_bot(db, bot_id)
        derived = (file_name or url).strip() or url
        document = await self.create_pending_document(
            db,
            bot_id,
            file_name=derived,
            source_type="web",
            format_hint="url",
        )
        await db.commit()

        from app.tasks.rag_tasks import enqueue_document_ingest

        org_id = str(bot.organization_id) if bot.organization_id else None
        task_id = enqueue_document_ingest(
            bot_id=bot_id,
            document_id=document.id,
            filename=derived,
            content=b"",
            content_type="text/html",
            source_type="web",
            source_url=url.strip(),
            crawl_depth=max(1, min(crawl_depth, 5)),
            organization_id=org_id,
            metadata=metadata,
        )
        return {
            "task_id": task_id,
            "document_id": str(document.id),
            "bot_id": str(bot_id),
            "kb_id": str(bot_id),
            "status": KnowledgeDocumentStatus.PENDING.value,
        }

    async def set_status(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
        *,
        status: KnowledgeDocumentStatus,
        progress: int | None = None,
        error_message: str | None = None,
        character_count: int | None = None,
        chunk_count: int | None = None,
        clear_error: bool = False,
    ) -> KnowledgeBaseDocument | None:
        result = await db.execute(
            select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == document_id)
        )
        document = result.scalar_one_or_none()
        if document is None:
            return None

        document.status = status
        if progress is not None:
            document.progress = max(0, min(100, int(progress)))
        if clear_error:
            document.error_message = None
        elif error_message is not None:
            document.error_message = error_message[:4000]
        if character_count is not None:
            document.character_count = character_count
        if chunk_count is not None:
            document.chunk_count = chunk_count
        await db.flush()
        return document

    async def process_document(
        self,
        db: AsyncSession,
        *,
        document_id: uuid.UUID,
        bot_id: uuid.UUID,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        source_type: str = "file",
        source_url: str | None = None,
        crawl_depth: int = 1,
        organization_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run extract → embed → store; update lifecycle fields on the document row."""
        from app.services.document_parser import (
            extract_text_from_bytes,
            fetch_url_text,
            ingest_document_to_chroma,
        )

        document = await db.get(KnowledgeBaseDocument, document_id)
        if document is None:
            return {"ok": False, "error": "document_not_found", "document_id": str(document_id)}
        if document.bot_id != bot_id:
            logger.error(
                "RAG.ingest_bot_mismatch | document_id={doc} expected={expected} got={got}",
                doc=document_id,
                expected=document.bot_id,
                got=bot_id,
            )
            return {"ok": False, "error": "bot_mismatch", "document_id": str(document_id)}

        bot = await db.get(Bot, bot_id)
        if bot is None:
            return {"ok": False, "error": "bot_not_found", "document_id": str(document_id)}
        # Always derive org from the bot row — never trust task-supplied org alone.
        organization_id = str(bot.organization_id) if bot.organization_id else organization_id

        await self.set_status(
            db,
            document_id,
            status=KnowledgeDocumentStatus.PARSING,
            progress=10,
            clear_error=True,
        )
        await db.commit()

        try:
            if source_type == "web" and source_url:
                text = fetch_url_text(source_url, depth_limit=crawl_depth)
            else:
                text = extract_text_from_bytes(content, filename)

            await self.set_status(
                db,
                document_id,
                status=KnowledgeDocumentStatus.PARSING,
                progress=40,
                character_count=len(text),
            )
            await db.commit()

            if not text.strip():
                await self.set_status(
                    db,
                    document_id,
                    status=KnowledgeDocumentStatus.FAILED,
                    progress=100,
                    error_message="Text extraction produced empty content.",
                )
                await db.commit()
                return {"ok": False, "error": "empty_extract", "document_id": str(document_id)}

            await self.set_status(
                db,
                document_id,
                status=KnowledgeDocumentStatus.PARSING,
                progress=60,
            )
            await db.commit()

            kb_id = str(bot_id)
            org_id = organization_id
            if not org_id:
                bot = await db.get(Bot, bot_id)
                if bot and bot.organization_id:
                    org_id = str(bot.organization_id)

            source_meta: dict[str, Any] = {
                "document_id": str(document_id),
                "file_name": filename,
                "source_type": source_type,
                "content_type": content_type or "",
                "kb_id": kb_id,
                "bot_id": kb_id,
                **(metadata or {}),
            }
            if org_id:
                source_meta["organization_id"] = org_id

            ingest_result = await ingest_document_to_chroma(
                bot_id=kb_id,
                text=text,
                source_metadata=source_meta,
            )
            stored = int(ingest_result.get("chunks_stored") or 0)
            if stored <= 0:
                await self.set_status(
                    db,
                    document_id,
                    status=KnowledgeDocumentStatus.FAILED,
                    progress=100,
                    character_count=len(text),
                    chunk_count=0,
                    error_message="Embedding produced no chunks to store.",
                )
                await db.commit()
                return {"ok": False, "error": "no_chunks", "document_id": str(document_id)}

            await self.set_status(
                db,
                document_id,
                status=KnowledgeDocumentStatus.INDEXED,
                progress=100,
                character_count=len(text),
                chunk_count=stored,
                clear_error=True,
            )
            await db.commit()
            await knowledge_base_service.invalidate_retrieval_cache(bot_id)

            logger.info(
                "RAG.ingest_indexed | bot_id={bot_id} document_id={document_id} chunks={count} org={org}",
                bot_id=bot_id,
                document_id=document_id,
                count=stored,
                org=org_id,
            )
            return {
                "ok": True,
                "document_id": str(document_id),
                "bot_id": str(bot_id),
                "chunks_stored": stored,
                "chars": len(text),
                "collection": ingest_result.get("collection"),
            }
        except Exception as exc:
            logger.exception(
                "RAG.ingest_failed | document_id={document_id} error={error}",
                document_id=document_id,
                error=str(exc),
            )
            try:
                await self.set_status(
                    db,
                    document_id,
                    status=KnowledgeDocumentStatus.FAILED,
                    progress=100,
                    error_message=str(exc)[:4000],
                )
                await db.commit()
            except Exception:
                logger.exception("RAG.status_update_failed | document_id={document_id}", document_id=document_id)
            return {"ok": False, "error": str(exc), "document_id": str(document_id)}


knowledge_ingestion_service = KnowledgeIngestionService()
