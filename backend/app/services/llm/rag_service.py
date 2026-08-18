"""LLM Gateway RAG — chunking, embeddings, ingest, cosine similarity search."""

from __future__ import annotations

import math
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.llm.knowledge import KnowledgeBase, KnowledgeDocument

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]


class RAGServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class KnowledgeBaseNotFoundError(RAGServiceError):
    def __init__(self, message: str = "Knowledge base not found.") -> None:
        super().__init__(message, status_code=404)


class KnowledgeBaseConflictError(RAGServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in pure Python (pgvector-ready alternative)."""
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy
    if norm_a <= 0.0 or norm_b <= 0.0:
        return -1.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def chunk_text(
    text: str,
    *,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """
    Split text into overlapping character windows.

    Defaults come from ``KB_CHUNK_SIZE`` / ``KB_CHUNK_OVERLAP``.
    """
    size = int(chunk_size if chunk_size is not None else getattr(settings, "KB_CHUNK_SIZE", 500))
    ov = int(overlap if overlap is not None else getattr(settings, "KB_CHUNK_OVERLAP", 50))
    size = max(50, size)
    ov = max(0, min(ov, size - 1))

    cleaned = (text or "").strip()
    if not cleaned:
        return []

    if len(cleaned) <= size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + size, length)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(0, end - ov)
        if start >= end:
            start = end
    return chunks


class RAGService:
    """
    Org-scoped RAG for the LLM Gateway.

    Embeddings default to OpenAI via ``app.core.embeddings.embed_texts``;
    inject ``embed_fn`` in tests to avoid network calls.
    """

    def __init__(self, *, embed_fn: EmbedFn | None = None) -> None:
        self._embed_fn = embed_fn

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embed_fn is not None:
            return await self._embed_fn(texts)
        from app.core.embeddings import embed_texts

        return await embed_texts(texts)

    async def create_knowledge_base(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        name: str,
    ) -> KnowledgeBase:
        cleaned = (name or "").strip()
        if not cleaned:
            raise RAGServiceError("Knowledge base name is required.")

        existing = await db.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.name == cleaned,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise KnowledgeBaseConflictError(
                f"Knowledge base '{cleaned}' already exists in this organization."
            )

        base = KnowledgeBase(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name=cleaned,
        )
        db.add(base)
        await db.flush()
        await db.commit()
        await db.refresh(base)
        logger.info(
            "LLM.RAG.create_base | org={org} id={id} name={name}",
            org=organization_id,
            id=base.id,
            name=cleaned,
        )
        return base

    async def list_knowledge_bases(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> list[KnowledgeBase]:
        result = await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.organization_id == organization_id)
            .order_by(KnowledgeBase.name.asc())
        )
        return list(result.scalars().all())

    async def get_knowledge_base(
        self,
        db: AsyncSession,
        base_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> KnowledgeBase:
        base = await db.get(KnowledgeBase, base_id)
        if base is None or base.organization_id != organization_id:
            raise KnowledgeBaseNotFoundError()
        return base

    async def ingest_document(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        base_id: uuid.UUID,
        *,
        file_name: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> dict[str, Any]:
        """Chunk → embed → persist ``KnowledgeDocument`` rows."""
        base = await self.get_knowledge_base(db, base_id, organization_id)
        fname = (file_name or "document.txt").strip() or "document.txt"
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            raise RAGServiceError("Document text is empty after chunking.")

        embeddings = await self._embed(chunks)
        if len(embeddings) != len(chunks):
            raise RAGServiceError("Embedding provider returned unexpected vector count.")

        saved: list[KnowledgeDocument] = []
        for index, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=True)):
            if not vector:
                raise RAGServiceError(f"Empty embedding for chunk {index}.")
            doc = KnowledgeDocument(
                id=uuid.uuid4(),
                knowledge_base_id=base.id,
                file_name=fname,
                content=chunk,
                embedding=[float(v) for v in vector],
                chunk_index=index,
                metadata_={
                    **(metadata or {}),
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "char_count": len(chunk),
                },
            )
            db.add(doc)
            saved.append(doc)

        await db.flush()
        await db.commit()
        for doc in saved:
            await db.refresh(doc)

        logger.info(
            "LLM.RAG.ingest | org={org} base={base} file={file} chunks={n}",
            org=organization_id,
            base=base_id,
            file=fname,
            n=len(saved),
        )
        return {
            "knowledge_base_id": base.id,
            "file_name": fname,
            "chunks_stored": len(saved),
            "document_ids": [d.id for d in saved],
        }

    async def similarity_search(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        base_id: uuid.UUID,
        query: str,
        *,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Embed query and rank chunks by cosine similarity (desc)."""
        await self.get_knowledge_base(db, base_id, organization_id)
        cleaned = (query or "").strip()
        if not cleaned:
            raise RAGServiceError("Search query must not be empty.")

        k = int(top_k if top_k is not None else getattr(settings, "RAG_TOP_K", 3))
        k = max(1, min(k, 50))

        query_vectors = await self._embed([cleaned])
        query_vec = query_vectors[0]

        result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == base_id)
        )
        docs = list(result.scalars().all())
        scored: list[tuple[float, KnowledgeDocument]] = []
        for doc in docs:
            score = cosine_similarity(query_vec, list(doc.embedding or []))
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)

        hits: list[dict[str, Any]] = []
        for score, doc in scored[:k]:
            hits.append(
                {
                    "id": doc.id,
                    "file_name": doc.file_name,
                    "content": doc.content,
                    "score": round(float(score), 6),
                    "chunk_index": doc.chunk_index,
                    "metadata": doc.metadata_ or {},
                }
            )
        return hits


rag_service = RAGService()
