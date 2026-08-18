"""RAG ingest + retrieval façade with tenant-aware metadata."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.vector_db import similarity_search, similarity_search_detailed
from app.services.document_parser import (
    bot_collection_name,
    extract_text_from_bytes,
    ingest_document_to_chroma,
)


class RAGService:
    """
    Ingest PDF/Docx → chunk → embed → Chroma (bot-scoped collection).

    Metadata always includes ``organization_id`` / ``bot_id`` so callers can
    filter by tenant at query time.
    """

    def collection_name(self, bot_id: uuid.UUID | str) -> str:
        return bot_collection_name(str(bot_id))

    async def ingest_file(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        filename: str,
        content: bytes,
        source_type: str = "file",
    ) -> dict[str, Any]:
        _ = db  # reserved for KnowledgeBaseDocument persistence by callers
        text = extract_text_from_bytes(content, filename)
        summary = await ingest_document_to_chroma(
            str(bot_id),
            text,
            source_metadata={
                "file_name": filename,
                "source_type": source_type,
                "bot_id": str(bot_id),
                "organization_id": str(organization_id) if organization_id else "",
            },
        )
        logger.info(
            "RAGService.ingest | bot_id={bot_id} file={file} chunks={chunks}",
            bot_id=bot_id,
            file=filename,
            chunks=summary.get("chunks_stored"),
        )
        return {
            **summary,
            "character_count": len(text),
            "chunk_count": summary.get("chunks_stored", 0),
        }

    async def search(
        self,
        *,
        bot_id: uuid.UUID,
        query: str,
        top_k: int | None = None,
        organization_id: uuid.UUID | None = None,
        knowledge_base_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve chunks for a bot.

        Prefer ``knowledge_base_id`` when provided; otherwise use bot collection name.
        Tenant filter is applied post-query on metadata when ``organization_id`` is set.
        """
        k = top_k or settings.RAG_TOP_K
        kb = knowledge_base_id or self.collection_name(bot_id)

        try:
            detailed = await similarity_search_detailed(kb, query, top_k=k)
            results: list[dict[str, Any]] = []
            for hit in detailed:
                meta = getattr(hit, "metadata", None) or {}
                if not isinstance(meta, dict):
                    meta = {}
                if organization_id is not None:
                    org = str(meta.get("organization_id") or "")
                    if org and org != str(organization_id):
                        continue
                text = getattr(hit, "text", None) or getattr(hit, "document", None) or str(hit)
                results.append(
                    {
                        "text": text,
                        "metadata": meta,
                        "score": getattr(hit, "score", None)
                        or getattr(hit, "distance", None),
                    }
                )
            if results:
                return results
        except Exception as exc:
            logger.debug("RAGService.detailed_fallback | error={error}", error=str(exc))

        texts = await similarity_search(kb, query, top_k=k)
        return [{"text": t, "metadata": {"bot_id": str(bot_id)}, "score": None} for t in texts]


rag_service = RAGService()
