from __future__ import annotations

import asyncio
import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_cache import llm_response_cache
from app.core.rag_cache import BotDocumentActivationSnapshot, rag_activation_cache
from app.core.vector_db import delete_document_vectors, list_document_chunks
from app.models.core_models import Bot, KnowledgeBaseDocument, KnowledgeDocumentStatus
from app.schemas.knowledge_base_schemas import (
    KnowledgeBaseChunksResponse,
    KnowledgeBaseChunkItem,
    KnowledgeBaseDeleteResponse,
    KnowledgeBaseDocumentContextResponse,
    KnowledgeBaseDocumentItem,
    KnowledgeBaseDocumentListResponse,
    KnowledgeBaseUploadResponse,
)
from app.services.document_parser import ingest_document_to_chroma, split_text_into_chunks


def _document_status_value(document: KnowledgeBaseDocument) -> str:
    status = getattr(document, "status", None)
    if status is None:
        return "INDEXED"
    return status.value if hasattr(status, "value") else str(status)


class KnowledgeBaseService:
    """Manage per-bot knowledge base uploads, listing, and vector cleanup."""

    @staticmethod
    def knowledge_base_id_for_bot(bot_id: uuid.UUID) -> str:
        return str(bot_id)

    @staticmethod
    async def invalidate_retrieval_cache(bot_id: uuid.UUID) -> None:
        """Drop in-memory RAG snapshot and Redis LLM responses for this bot."""
        rag_activation_cache.invalidate(bot_id)
        await llm_response_cache.invalidate_bot_cache(bot_id)
        logger.debug(
            "KnowledgeBase.rag_cache_invalidated | bot_id={bot_id}",
            bot_id=bot_id,
        )

    async def list_documents(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> KnowledgeBaseDocumentListResponse:
        await self._get_bot(db, bot_id)
        result = await db.execute(
            select(KnowledgeBaseDocument)
            .where(KnowledgeBaseDocument.bot_id == bot_id)
            .order_by(KnowledgeBaseDocument.created_at.desc())
        )
        documents = result.scalars().all()
        items = [
            KnowledgeBaseDocumentItem(
                id=document.id,
                bot_id=document.bot_id,
                file_name=document.file_name,
                source_type=(
                    document.source_type
                    if document.source_type in {"file", "text", "web", "google_drive"}
                    else "file"
                ),
                format=getattr(document, "format", None),
                character_count=document.character_count,
                chunk_count=document.chunk_count,
                is_context_active=bool(document.is_context_active),
                status=_document_status_value(document),  # type: ignore[arg-type]
                progress=int(getattr(document, "progress", 100) or 100),
                error_message=getattr(document, "error_message", None),
                created_at=document.created_at,
            )
            for document in documents
        ]
        logger.info(
            "KnowledgeBase.list_documents | bot_id={bot_id} total={total}",
            bot_id=bot_id,
            total=len(items),
        )
        return KnowledgeBaseDocumentListResponse(
            bot_id=bot_id,
            knowledge_base_id=self.knowledge_base_id_for_bot(bot_id),
            documents=items,
            total=len(items),
        )

    async def upload_text(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        raw_text: str,
        file_name: str,
        source_type: str = "text",
    ) -> KnowledgeBaseUploadResponse:
        bot = await self._get_bot(db, bot_id)
        knowledge_base_id = self.knowledge_base_id_for_bot(bot.id)
        normalized_name = file_name.strip() or "pasted-text.txt"
        character_count = len(raw_text)

        # CPU-bound chunking — keep the FastAPI event loop free.
        chunks = await asyncio.to_thread(split_text_into_chunks, raw_text)
        if not chunks:
            logger.warning(
                "KnowledgeBase.upload_empty | bot_id={bot_id} file_name={file_name}",
                bot_id=bot_id,
                file_name=normalized_name,
            )
            raise ValueError("Provided document contains no usable text after processing.")

        document = KnowledgeBaseDocument(
            bot_id=bot.id,
            file_name=normalized_name,
            source_type=source_type,
            character_count=character_count,
            chunk_count=0,
            is_context_active=True,
            status=KnowledgeDocumentStatus.PARSING,
            progress=20,
            error_message=None,
        )
        db.add(document)
        await db.flush()

        try:
            org_id = str(bot.organization_id) if bot.organization_id else None
            ingest_result = await ingest_document_to_chroma(
                bot_id=knowledge_base_id,
                text=raw_text,
                source_metadata={
                    "document_id": str(document.id),
                    "file_name": normalized_name,
                    "source_type": source_type,
                    "kb_id": knowledge_base_id,
                    "bot_id": knowledge_base_id,
                    **({"organization_id": org_id} if org_id else {}),
                },
            )
            stored_chunks = int(ingest_result.get("chunks_stored") or 0)
        except Exception as exc:
            document.status = KnowledgeDocumentStatus.FAILED
            document.progress = 100
            document.error_message = str(exc)[:4000]
            await db.flush()
            logger.exception(
                "KnowledgeBase.upload_failed | bot_id={bot_id} document_id={document_id} error={error}",
                bot_id=bot_id,
                document_id=document.id,
                error=str(exc),
            )
            raise ValueError("Failed to store knowledge base document in vector store.") from exc

        document.chunk_count = stored_chunks
        document.status = KnowledgeDocumentStatus.INDEXED
        document.progress = 100
        document.error_message = None
        await db.flush()
        await self.invalidate_retrieval_cache(bot_id)

        logger.info(
            "KnowledgeBase.upload_success | bot_id={bot_id} document_id={document_id} chunks={count}",
            bot_id=bot_id,
            document_id=document.id,
            count=stored_chunks,
        )
        return KnowledgeBaseUploadResponse(
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            file_name=normalized_name,
            character_count=character_count,
            chunks_stored=stored_chunks,
        )

    async def reindex_document(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        crawl_depth: int = 1,
    ) -> KnowledgeBaseUploadResponse:
        await self._get_bot(db, bot_id)
        result = await db.execute(
            select(KnowledgeBaseDocument).where(
                KnowledgeBaseDocument.id == document_id,
                KnowledgeBaseDocument.bot_id == bot_id,
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise ValueError(f"Document '{document_id}' not found for bot '{bot_id}'.")

        if document.source_type != "web":
            raise ValueError("Reindex is currently supported for web (URL) documents only.")

        from app.services.document_parser import fetch_url_text

        # Blocking HTTP crawl + chunking must not stall the event loop.
        crawled_text = await asyncio.to_thread(
            fetch_url_text,
            document.file_name,
            depth_limit=crawl_depth,
        )
        knowledge_base_id = self.knowledge_base_id_for_bot(bot_id)

        try:
            # Chroma delete/add/query run via asyncio.to_thread inside vector_db.
            await delete_document_vectors(str(document.id), bot_id=knowledge_base_id)
        except Exception as exc:
            logger.exception(
                "KnowledgeBase.reindex_purge_failed | bot_id={bot_id} document_id={document_id} error={error}",
                bot_id=bot_id,
                document_id=document_id,
                error=str(exc),
            )
            raise ValueError("Failed to purge existing vectors before reindex.") from exc

        chunks = await asyncio.to_thread(split_text_into_chunks, crawled_text)
        if not chunks:
            raise ValueError("Crawled website contains no usable text after processing.")

        try:
            ingest_result = await ingest_document_to_chroma(
                bot_id=knowledge_base_id,
                text=crawled_text,
                source_metadata={
                    "document_id": str(document.id),
                    "file_name": document.file_name,
                    "source_type": "web",
                },
            )
            stored_chunks = int(ingest_result.get("chunks_stored") or 0)
        except Exception as exc:
            logger.exception(
                "KnowledgeBase.reindex_store_failed | bot_id={bot_id} document_id={document_id} error={error}",
                bot_id=bot_id,
                document_id=document_id,
                error=str(exc),
            )
            raise ValueError("Failed to store reindexed document in vector store.") from exc

        document.character_count = len(crawled_text)
        document.chunk_count = stored_chunks
        await db.flush()
        await self.invalidate_retrieval_cache(bot_id)

        logger.info(
            "KnowledgeBase.reindex_success | bot_id={bot_id} document_id={document_id} chunks={count}",
            bot_id=bot_id,
            document_id=document_id,
            count=stored_chunks,
        )
        return KnowledgeBaseUploadResponse(
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            file_name=document.file_name,
            character_count=document.character_count,
            chunks_stored=stored_chunks,
            message="Document reindexed successfully.",
        )

    async def delete_document(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> KnowledgeBaseDeleteResponse:
        bot = await self._get_bot(db, bot_id)
        result = await db.execute(
            select(KnowledgeBaseDocument).where(
                KnowledgeBaseDocument.id == document_id,
                KnowledgeBaseDocument.bot_id == bot_id,
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            logger.warning(
                "KnowledgeBase.delete_not_found | bot_id={bot_id} document_id={document_id}",
                bot_id=bot_id,
                document_id=document_id,
            )
            raise ValueError(f"Document '{document_id}' not found for bot '{bot_id}'.")

        try:
            org_id = str(bot.organization_id) if bot.organization_id else None
            vectors_removed = await delete_document_vectors(
                str(document.id),
                bot_id=str(bot_id),
                organization_id=org_id,
            )
        except Exception as exc:
            logger.exception(
                "KnowledgeBase.delete_vectors_failed | bot_id={bot_id} document_id={document_id} error={error}",
                bot_id=bot_id,
                document_id=document_id,
                error=str(exc),
            )
            raise ValueError("Failed to remove document vectors from vector store.") from exc

        await db.delete(document)
        await db.flush()
        await self.invalidate_retrieval_cache(bot_id)

        logger.info(
            "KnowledgeBase.delete_success | bot_id={bot_id} document_id={document_id} vectors_removed={count}",
            bot_id=bot_id,
            document_id=document_id,
            count=vectors_removed,
        )
        return KnowledgeBaseDeleteResponse(
            bot_id=bot_id,
            document_id=document_id,
            deleted=True,
            vectors_removed=vectors_removed,
        )

    async def set_document_context_active(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        is_context_active: bool,
    ) -> KnowledgeBaseDocumentContextResponse:
        await self._get_bot(db, bot_id)
        result = await db.execute(
            select(KnowledgeBaseDocument).where(
                KnowledgeBaseDocument.id == document_id,
                KnowledgeBaseDocument.bot_id == bot_id,
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise ValueError(f"Document '{document_id}' not found for bot '{bot_id}'.")

        document.is_context_active = is_context_active
        await db.flush()
        # Ensure subsequent RAG turns never serve stale activation membership.
        await self.invalidate_retrieval_cache(bot_id)

        logger.info(
            "KnowledgeBase.context_updated | bot_id={bot_id} document_id={document_id} active={active}",
            bot_id=bot_id,
            document_id=document_id,
            active=is_context_active,
        )
        return KnowledgeBaseDocumentContextResponse(
            bot_id=bot_id,
            document_id=document_id,
            is_context_active=is_context_active,
            message="Document search visibility updated.",
        )

    async def get_document_chunks(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> KnowledgeBaseChunksResponse:
        await self._get_bot(db, bot_id)
        result = await db.execute(
            select(KnowledgeBaseDocument).where(
                KnowledgeBaseDocument.id == document_id,
                KnowledgeBaseDocument.bot_id == bot_id,
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise ValueError(f"Document '{document_id}' not found for bot '{bot_id}'.")

        stored_chunks = await list_document_chunks(str(document.id), bot_id=str(bot_id))
        chunks = [
            KnowledgeBaseChunkItem(
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                similarity_weight=chunk["similarity_weight"],
            )
            for chunk in stored_chunks
        ]
        return KnowledgeBaseChunksResponse(
            bot_id=bot_id,
            document_id=document.id,
            file_name=document.file_name,
            chunks=chunks,
            total=len(chunks),
        )

    async def get_activation_snapshot(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> BotDocumentActivationSnapshot:
        """Return cached or freshly loaded active / inactive document ID sets."""
        cached = rag_activation_cache.get(bot_id)
        if cached is not None:
            return cached

        result = await db.execute(
            select(KnowledgeBaseDocument.id, KnowledgeBaseDocument.is_context_active).where(
                KnowledgeBaseDocument.bot_id == bot_id,
            )
        )
        active_document_ids: list[str] = []
        inactive_document_ids: list[str] = []
        for document_id, is_active in result.all():
            serialized = str(document_id)
            if bool(is_active):
                active_document_ids.append(serialized)
            else:
                inactive_document_ids.append(serialized)

        return rag_activation_cache.put(
            bot_id,
            active_document_ids=active_document_ids,
            inactive_document_ids=inactive_document_ids,
        )

    async def get_active_document_ids(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> list[str]:
        snapshot = await self.get_activation_snapshot(db, bot_id)
        return list(snapshot.active_document_ids)

    async def get_inactive_document_ids(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> list[str]:
        """PostgreSQL IDs where ``is_context_active = False`` for Chroma ``$nin`` filters."""
        snapshot = await self.get_activation_snapshot(db, bot_id)
        return list(snapshot.inactive_document_ids)

    async def _get_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Bot:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot is None:
            logger.warning("KnowledgeBase.bot_not_found | bot_id={bot_id}", bot_id=bot_id)
            raise ValueError(f"Bot with id '{bot_id}' not found.")
        return bot


knowledge_base_service = KnowledgeBaseService()
