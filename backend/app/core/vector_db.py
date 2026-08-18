from __future__ import annotations

import asyncio
import re
import uuid
from functools import lru_cache
from typing import Any, TypedDict

import chromadb
from chromadb.api.models.Collection import Collection
from loguru import logger

from app.core.config import settings
from app.core.embeddings import embed_text, embed_texts
from app.services.rag.collections import build_org_where_filter, org_collection_name


class RAGSearchHit(TypedDict):
    text: str
    similarity_score: float
    document_id: str | None
    file_name: str | None
    chunk_index: int | None
    page_number: int | None
    section: str | None
    # Optional media URLs persisted in Chroma metadata at ingest time.
    source_file_url: str | None
    image_attachment: str | None
    file_url: str | None
    media_url: str | None
    metadata: dict[str, Any]


class StoredChunkHit(TypedDict):
    chunk_index: int
    text: str
    similarity_weight: float


# Chroma `where` payloads are loosely typed at the SDK boundary; keep our builders strict.
ChromaWhereFilter = dict[str, Any]


def bot_collection_name(bot_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", str(bot_id).strip())
    return f"bot_{cleaned}"[:128]


def _get_org_collection(org_id: str) -> Collection:
    """Tenant-isolated Chroma collection ``org_{org_id}``."""
    client = _get_chroma_client()
    name = org_collection_name(org_id)
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine", "organization_id": str(org_id)},
    )


def build_rag_where_filter(
    knowledge_base_id: str,
    *,
    allowed_document_ids: list[str] | None = None,
    excluded_document_ids: list[str] | None = None,
) -> ChromaWhereFilter | None:
    """Build a typed Chroma metadata filter for RAG queries.

    Returns ``None`` when the caller should skip the vector lookup entirely
    (e.g. zero active documents — avoids Chroma errors on empty ``$in`` / ``$nin``).
    """
    kb_clause: dict[str, str] = {"knowledge_base_id": knowledge_base_id}

    if allowed_document_ids is not None:
        if len(allowed_document_ids) == 0:
            return None
        return {
            "$and": [
                kb_clause,
                {"document_id": {"$in": list(allowed_document_ids)}},
            ]
        }

    if excluded_document_ids:
        return {
            "$and": [
                kb_clause,
                {"document_id": {"$nin": list(excluded_document_ids)}},
            ]
        }

    return dict(kb_clause)


@lru_cache(maxsize=1)
def _get_chroma_client() -> Any:
    """Create the shared Chroma client (sync SDK — call only from worker threads)."""
    server_host = settings.CHROMA_SERVER_HOST
    if server_host:
        logger.info(
            "VectorDB.init | mode=http host={host} port={port}",
            host=server_host,
            port=settings.CHROMA_SERVER_PORT,
        )
        return chromadb.HttpClient(
            host=server_host,
            port=settings.CHROMA_SERVER_PORT,
        )

    logger.info(
        "VectorDB.init | mode=persistent path={path}",
        path=settings.CHROMA_PERSIST_DIRECTORY,
    )
    return chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIRECTORY)


def _get_collection() -> Collection:
    client = _get_chroma_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _get_bot_collection(bot_id: str) -> Collection:
    """Isolated per-bot Chroma collection (``bot_{bot_id}``)."""
    client = _get_chroma_client()
    name = bot_collection_name(bot_id)
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine", "bot_id": str(bot_id)},
    )


def _sync_add_chunks_to_bot_collection(
    bot_id: str,
    document_id: str,
    file_name: str,
    text_chunks: list[str],
    embeddings: list[list[float]],
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    collection = _get_bot_collection(bot_id)
    ids = [f"{document_id}:{index}" for index in range(len(text_chunks))]
    extras = {
        key: value
        for key, value in (extra_metadata or {}).items()
        if value is not None and isinstance(value, (str, int, float, bool))
    }
    # Avoid duplicating reserved keys from caller metadata.
    for reserved in ("bot_id", "document_id", "file_name", "chunk_index", "knowledge_base_id"):
        extras.pop(reserved, None)

    metadatas: list[dict[str, Any]] = [
        {
            "bot_id": str(bot_id),
            "knowledge_base_id": str(bot_id),
            "document_id": document_id,
            "file_name": file_name,
            "chunk_index": index,
            **extras,
        }
        for index, _ in enumerate(text_chunks)
    ]

    # Replace prior vectors for this document inside the bot collection.
    try:
        existing = collection.get(where={"document_id": document_id}, include=["metadatas"])
        existing_ids = existing.get("ids") or []
        if existing_ids:
            collection.delete(ids=existing_ids)
    except Exception as exc:
        logger.warning(
            "VectorDB.bot_collection_replace_skipped | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=document_id,
            error=str(exc),
        )

    collection.add(
        ids=ids,
        documents=text_chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    # Dual-write into org-scoped collection when organization_id is present.
    org_id = extras.get("organization_id") or (extra_metadata or {}).get("organization_id")
    if org_id:
        try:
            org_collection = _get_org_collection(str(org_id))
            try:
                prior = org_collection.get(where={"document_id": document_id}, include=["metadatas"])
                prior_ids = prior.get("ids") or []
                if prior_ids:
                    org_collection.delete(ids=prior_ids)
            except Exception:
                pass
            org_metadatas = [
                {
                    **meta,
                    "kb_id": str(meta.get("kb_id") or meta.get("knowledge_base_id") or bot_id),
                    "organization_id": str(org_id),
                }
                for meta in metadatas
            ]
            org_collection.add(
                ids=ids,
                documents=text_chunks,
                embeddings=embeddings,
                metadatas=org_metadatas,
            )
            logger.info(
                "VectorDB.org_collection_stored | org={org} collection={collection} document_id={document_id} chunks={count}",
                org=org_id,
                collection=org_collection_name(str(org_id)),
                document_id=document_id,
                count=len(text_chunks),
            )
        except Exception as exc:
            logger.warning(
                "VectorDB.org_collection_store_failed | org={org} error={error}",
                org=org_id,
                error=str(exc),
            )

    logger.info(
        "VectorDB.bot_collection_stored | bot_id={bot_id} collection={collection} document_id={document_id} chunks={count}",
        bot_id=bot_id,
        collection=bot_collection_name(bot_id),
        document_id=document_id,
        count=len(text_chunks),
    )
    return len(text_chunks)


async def add_chunks_to_bot_collection(
    *,
    bot_id: str,
    document_id: str,
    file_name: str,
    text_chunks: list[str],
    embeddings: list[list[float]],
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    cleaned = [chunk.strip() for chunk in text_chunks if chunk and chunk.strip()]
    if not cleaned:
        return 0
    if len(embeddings) != len(cleaned):
        raise ValueError("embeddings length must match text_chunks length")
    return await asyncio.to_thread(
        _sync_add_chunks_to_bot_collection,
        bot_id,
        document_id,
        file_name,
        cleaned,
        embeddings,
        extra_metadata,
    )


def _sync_add_chunks(
    knowledge_base_id: str,
    document_id: str,
    file_name: str,
    text_chunks: list[str],
    embeddings: list[list[float]],
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    collection = _get_collection()
    ids = [f"{document_id}:{index}" for index in range(len(text_chunks))]
    extras = {
        key: value
        for key, value in (extra_metadata or {}).items()
        if value is not None and isinstance(value, (str, int, float, bool))
    }
    metadatas: list[dict[str, Any]] = [
        {
            "knowledge_base_id": knowledge_base_id,
            "document_id": document_id,
            "file_name": file_name,
            "chunk_index": index,
            **extras,
        }
        for index, _ in enumerate(text_chunks)
    ]

    collection.add(
        ids=ids,
        documents=text_chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def _build_document_only_where(
    *,
    allowed_document_ids: list[str] | None = None,
    excluded_document_ids: list[str] | None = None,
) -> ChromaWhereFilter | None:
    """Metadata filter for an isolated bot collection (no knowledge_base_id clause)."""
    if allowed_document_ids is not None:
        if len(allowed_document_ids) == 0:
            return None
        return {"document_id": {"$in": list(allowed_document_ids)}}
    if excluded_document_ids:
        return {"document_id": {"$nin": list(excluded_document_ids)}}
    return {}


def _hits_from_query_result(results: dict[str, Any]) -> list[RAGSearchHit]:
    documents_nested = results.get("documents") or [[]]
    documents = documents_nested[0] if documents_nested else []
    distances_nested = results.get("distances") or [[]]
    distances = distances_nested[0] if distances_nested else []
    metadatas_nested = results.get("metadatas") or [[]]
    metadatas = metadatas_nested[0] if metadatas_nested else []

    hits: list[RAGSearchHit] = []
    for document, distance, metadata in zip(documents, distances, metadatas, strict=False):
        if not document:
            continue
        metadata = metadata or {}
        cosine_distance = float(distance or 1.0)
        similarity = max(0.0, min(1.0, 1.0 - cosine_distance))
        chunk_index = metadata.get("chunk_index")
        page_raw = metadata.get("page_number") or metadata.get("page")
        section_raw = metadata.get("section")

        def _meta_str(key: str) -> str | None:
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            return None

        hits.append(
            {
                "text": str(document),
                "similarity_score": round(similarity, 4),
                "document_id": metadata.get("document_id"),
                "file_name": metadata.get("file_name"),
                "chunk_index": int(chunk_index) if chunk_index is not None else None,
                "page_number": int(page_raw) if page_raw is not None and str(page_raw).isdigit() else None,
                "section": str(section_raw) if section_raw is not None else (
                    f"chunk-{chunk_index}" if chunk_index is not None else None
                ),
                "source_file_url": _meta_str("source_file_url"),
                "image_attachment": _meta_str("image_attachment"),
                "file_url": _meta_str("file_url"),
                "media_url": _meta_str("media_url"),
                "metadata": dict(metadata),
            },
        )
    return hits


def _merge_rag_hits(hits: list[RAGSearchHit], top_k: int) -> list[RAGSearchHit]:
    seen: set[tuple[str | None, int | None, str]] = set()
    unique: list[RAGSearchHit] = []
    for hit in sorted(hits, key=lambda item: item["similarity_score"], reverse=True):
        key = (hit.get("document_id"), hit.get("chunk_index"), hit["text"][:80])
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
        if len(unique) >= top_k:
            break
    return unique


def _sync_delete_from_collection(collection: Collection, document_id: str) -> int:
    existing = collection.get(
        where={"document_id": document_id},
        include=["metadatas"],
    )
    ids = existing.get("ids") or []
    if not ids:
        return 0
    collection.delete(where={"document_id": document_id})
    return len(ids)


def _sync_delete_document_vectors(
    document_id: str,
    bot_id: str | None = None,
    organization_id: str | None = None,
) -> int:
    removed = 0

    # Legacy shared collection (pre–per-bot isolation).
    try:
        removed += _sync_delete_from_collection(_get_collection(), document_id)
    except Exception as exc:
        logger.warning(
            "VectorDB.delete_shared_failed | document_id={document_id} error={error}",
            document_id=document_id,
            error=str(exc),
        )

    # Isolated bot collection.
    if bot_id:
        try:
            removed += _sync_delete_from_collection(_get_bot_collection(bot_id), document_id)
        except Exception as exc:
            logger.warning(
                "VectorDB.delete_bot_collection_failed | bot_id={bot_id} document_id={document_id} error={error}",
                bot_id=bot_id,
                document_id=document_id,
                error=str(exc),
            )

    # Org-scoped tenant collection.
    if organization_id:
        try:
            removed += _sync_delete_from_collection(
                _get_org_collection(str(organization_id)),
                document_id,
            )
        except Exception as exc:
            logger.warning(
                "VectorDB.delete_org_collection_failed | org={org} document_id={document_id} error={error}",
                org=organization_id,
                document_id=document_id,
                error=str(exc),
            )

    if removed == 0:
        logger.info(
            "VectorDB.delete_document_skipped | document_id={document_id} reason=no_vectors",
            document_id=document_id,
        )
    else:
        logger.info(
            "VectorDB.delete_document | document_id={document_id} bot_id={bot_id} vectors_removed={count}",
            document_id=document_id,
            bot_id=bot_id,
            count=removed,
        )
    return removed


def _rows_from_get_result(existing: dict[str, Any]) -> list[StoredChunkHit]:
    documents = existing.get("documents") or []
    metadatas = existing.get("metadatas") or []

    rows: list[StoredChunkHit] = []
    for document, metadata in zip(documents, metadatas, strict=False):
        if not document:
            continue
        metadata = metadata or {}
        chunk_index = int(metadata.get("chunk_index") or len(rows))
        text = str(document)
        char_factor = min(1.0, len(text) / 1200)
        order_factor = max(0.55, 1.0 - chunk_index * 0.035)
        similarity_weight = round(min(1.0, order_factor * (0.75 + char_factor * 0.25)), 4)
        rows.append(
            {
                "chunk_index": chunk_index,
                "text": text,
                "similarity_weight": similarity_weight,
            }
        )
    rows.sort(key=lambda item: item["chunk_index"])
    return rows


def _sync_list_document_chunks(document_id: str, bot_id: str | None = None) -> list[StoredChunkHit]:
    if bot_id:
        try:
            existing = _get_bot_collection(bot_id).get(
                where={"document_id": document_id},
                include=["documents", "metadatas"],
            )
            rows = _rows_from_get_result(existing)
            if rows:
                return rows
        except Exception as exc:
            logger.warning(
                "VectorDB.list_bot_chunks_failed | bot_id={bot_id} document_id={document_id} error={error}",
                bot_id=bot_id,
                document_id=document_id,
                error=str(exc),
            )

    existing = _get_collection().get(
        where={"document_id": document_id},
        include=["documents", "metadatas"],
    )
    return _rows_from_get_result(existing)


def _sync_query_chunks_detailed(
    knowledge_base_id: str,
    query_embedding: list[float],
    top_k: int,
    allowed_document_ids: list[str] | None = None,
    excluded_document_ids: list[str] | None = None,
    organization_id: str | None = None,
) -> list[RAGSearchHit]:
    merged: list[RAGSearchHit] = []

    # Prefer tenant-isolated org collection when organization_id is known.
    if organization_id:
        org_where = build_org_where_filter(
            bot_id=knowledge_base_id,
            kb_id=knowledge_base_id,
            allowed_document_ids=allowed_document_ids,
        )
        if org_where is not None:
            try:
                org_collection = _get_org_collection(str(organization_id))
                query_kwargs: dict[str, Any] = {
                    "query_embeddings": [query_embedding],
                    "n_results": top_k,
                    "include": ["documents", "distances", "metadatas"],
                }
                if org_where:
                    query_kwargs["where"] = org_where
                org_results = org_collection.query(**query_kwargs)
                merged.extend(_hits_from_query_result(org_results))
            except Exception as exc:
                logger.warning(
                    "VectorDB.org_query_failed | org={org} kb_id={kb_id} error={error}",
                    org=organization_id,
                    kb_id=knowledge_base_id,
                    error=str(exc),
                )

    # Isolated per-bot collection (backward compatible).
    bot_where = _build_document_only_where(
        allowed_document_ids=allowed_document_ids,
        excluded_document_ids=excluded_document_ids,
    )
    if bot_where is not None:
        try:
            bot_collection = _get_bot_collection(knowledge_base_id)
            query_kwargs: dict[str, Any] = {
                "query_embeddings": [query_embedding],
                "n_results": top_k,
                "include": ["documents", "distances", "metadatas"],
            }
            if bot_where:
                query_kwargs["where"] = bot_where
            bot_results = bot_collection.query(**query_kwargs)
            merged.extend(_hits_from_query_result(bot_results))
        except Exception as exc:
            logger.warning(
                "VectorDB.bot_query_failed | bot_id={bot_id} error={error}",
                bot_id=knowledge_base_id,
                error=str(exc),
            )

    # Fallback / merge with legacy shared collection for older uploads.
    shared_where = build_rag_where_filter(
        knowledge_base_id,
        allowed_document_ids=allowed_document_ids,
        excluded_document_ids=excluded_document_ids,
    )
    if shared_where is not None:
        try:
            shared_results = _get_collection().query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=shared_where,
                include=["documents", "distances", "metadatas"],
            )
            merged.extend(_hits_from_query_result(shared_results))
        except Exception as exc:
            logger.warning(
                "VectorDB.shared_query_failed | knowledge_base_id={kb_id} error={error}",
                kb_id=knowledge_base_id,
                error=str(exc),
            )

    hits = _merge_rag_hits(merged, top_k)
    logger.info(
        "VectorDB.search_detailed | knowledge_base_id={kb_id} hits={count} top_k={top_k} org={org}",
        kb_id=knowledge_base_id,
        count=len(hits),
        top_k=top_k,
        org=organization_id,
    )
    return hits


def _sync_query_chunks(
    knowledge_base_id: str,
    query_embedding: list[float],
    top_k: int,
    allowed_document_ids: list[str] | None = None,
    excluded_document_ids: list[str] | None = None,
) -> list[str]:
    hits = _sync_query_chunks_detailed(
        knowledge_base_id,
        query_embedding,
        top_k,
        allowed_document_ids,
        excluded_document_ids,
    )
    for index, hit in enumerate(hits):
        logger.debug(
            "VectorDB.hit | rank={rank} score={score} preview={preview!r}",
            rank=index + 1,
            score=hit["similarity_score"],
            preview=hit["text"][:80],
        )
    return [hit["text"] for hit in hits]

async def embed_and_store_document(
    knowledge_base_id: str,
    document_id: str,
    file_name: str,
    text_chunks: list[str],
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    """Generate embeddings for text chunks and persist them in the vector store."""
    cleaned_chunks = [chunk.strip() for chunk in text_chunks if chunk and chunk.strip()]
    logger.info(
        "VectorDB.embed_and_store | knowledge_base_id={kb_id} document_id={document_id} chunks={count}",
        kb_id=knowledge_base_id,
        document_id=document_id,
        count=len(cleaned_chunks),
    )

    if not cleaned_chunks:
        logger.warning(
            "VectorDB.embed_and_store_skipped | knowledge_base_id={kb_id} document_id={document_id} reason=empty_chunks",
            kb_id=knowledge_base_id,
            document_id=document_id,
        )
        return 0

    try:
        embeddings = await embed_texts(cleaned_chunks)
        await asyncio.to_thread(
            _sync_add_chunks,
            knowledge_base_id,
            document_id,
            file_name,
            cleaned_chunks,
            embeddings,
            extra_metadata,
        )
        logger.info(
            "VectorDB.stored | knowledge_base_id={kb_id} document_id={document_id} chunks={count}",
            kb_id=knowledge_base_id,
            document_id=document_id,
            count=len(cleaned_chunks),
        )
        return len(cleaned_chunks)
    except Exception as exc:
        logger.exception(
            "VectorDB.embed_and_store_failed | knowledge_base_id={kb_id} document_id={document_id} error={error}",
            kb_id=knowledge_base_id,
            document_id=document_id,
            error=str(exc),
        )
        raise


async def delete_document_vectors(
    document_id: str,
    *,
    bot_id: str | None = None,
    organization_id: str | None = None,
) -> int:
    """Remove all vector chunks associated with a document ID.

    When ``bot_id`` / ``organization_id`` are provided, also clears
    ``bot_{bot_id}`` and ``org_{organization_id}`` collections.
    """
    try:
        return await asyncio.to_thread(
            _sync_delete_document_vectors,
            document_id,
            bot_id,
            organization_id,
        )
    except Exception as exc:
        logger.exception(
            "VectorDB.delete_document_failed | document_id={document_id} error={error}",
            document_id=document_id,
            error=str(exc),
        )
        raise


def _sync_purge_bot_vectors(
    bot_id: str,
    *,
    organization_id: str | None = None,
    document_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Drop the isolated bot collection and scrub org/shared vectors for this bot."""
    client = _get_chroma_client()
    collection_name = bot_collection_name(bot_id)
    dropped = False
    removed_from_org = 0
    removed_from_shared = 0

    try:
        client.delete_collection(name=collection_name)
        dropped = True
        logger.info(
            "VectorDB.bot_collection_dropped | bot_id={bot_id} collection={name}",
            bot_id=bot_id,
            name=collection_name,
        )
    except Exception as exc:
        # Collection may not exist yet — treat as success.
        logger.info(
            "VectorDB.bot_collection_drop_skipped | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )

    ids = [str(doc_id) for doc_id in (document_ids or []) if doc_id]
    if ids:
        for document_id in ids:
            try:
                removed_from_shared += _sync_delete_from_collection(
                    _get_collection(),
                    document_id,
                )
            except Exception as exc:
                logger.warning(
                    "VectorDB.purge_shared_failed | document_id={document_id} error={error}",
                    document_id=document_id,
                    error=str(exc),
                )
            if organization_id:
                try:
                    removed_from_org += _sync_delete_from_collection(
                        _get_org_collection(str(organization_id)),
                        document_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "VectorDB.purge_org_failed | org={org} document_id={document_id} error={error}",
                        org=organization_id,
                        document_id=document_id,
                        error=str(exc),
                    )
    elif organization_id:
        # Best-effort wipe by bot_id metadata when document list is unavailable.
        try:
            org_collection = _get_org_collection(str(organization_id))
            org_collection.delete(where={"bot_id": str(bot_id)})
            removed_from_org = -1  # unknown count
        except Exception as exc:
            logger.warning(
                "VectorDB.purge_org_by_bot_failed | org={org} bot_id={bot_id} error={error}",
                org=organization_id,
                bot_id=bot_id,
                error=str(exc),
            )

    return {
        "collection_dropped": dropped,
        "removed_from_org": removed_from_org,
        "removed_from_shared": removed_from_shared,
    }


async def purge_bot_vectors(
    bot_id: str,
    *,
    organization_id: str | None = None,
    document_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Purge all Chroma embeddings belonging to a bot."""
    try:
        return await asyncio.to_thread(
            _sync_purge_bot_vectors,
            str(bot_id),
            organization_id=str(organization_id) if organization_id else None,
            document_ids=document_ids,
        )
    except Exception as exc:
        logger.exception(
            "VectorDB.purge_bot_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise


async def list_document_chunks(
    document_id: str,
    *,
    bot_id: str | None = None,
) -> list[StoredChunkHit]:
    """Return all stored chunks for a document with display similarity weights."""
    try:
        return await asyncio.to_thread(_sync_list_document_chunks, document_id, bot_id)
    except Exception as exc:
        logger.exception(
            "VectorDB.list_document_chunks_failed | document_id={document_id} error={error}",
            document_id=document_id,
            error=str(exc),
        )
        raise


async def similarity_search(
    knowledge_base_id: str,
    query: str,
    top_k: int = 3,
    allowed_document_ids: list[str] | None = None,
    excluded_document_ids: list[str] | None = None,
) -> list[str]:
    """Retrieve the most relevant text chunks for a knowledge base and query."""
    if not query.strip():
        logger.warning(
            "VectorDB.search_skipped | knowledge_base_id={kb_id} reason=empty_query",
            kb_id=knowledge_base_id,
        )
        return []

    logger.debug(
        "VectorDB.similarity_search | knowledge_base_id={kb_id} top_k={top_k}",
        kb_id=knowledge_base_id,
        top_k=top_k,
    )

    try:
        query_embedding = await embed_text(query)
        return await asyncio.to_thread(
            _sync_query_chunks,
            knowledge_base_id,
            query_embedding,
            top_k,
            allowed_document_ids,
            excluded_document_ids,
        )
    except Exception as exc:
        logger.exception(
            "VectorDB.similarity_search_failed | knowledge_base_id={kb_id} error={error}",
            kb_id=knowledge_base_id,
            error=str(exc),
        )
        return []


async def similarity_search_detailed(
    knowledge_base_id: str,
    query: str,
    top_k: int = 3,
    allowed_document_ids: list[str] | None = None,
    excluded_document_ids: list[str] | None = None,
    organization_id: str | None = None,
) -> list[RAGSearchHit]:
    """Retrieve ranked chunks with metadata and similarity scores."""
    if not query.strip():
        return []

    try:
        query_embedding = await embed_text(query)
        return await asyncio.to_thread(
            _sync_query_chunks_detailed,
            knowledge_base_id,
            query_embedding,
            top_k,
            allowed_document_ids,
            excluded_document_ids,
            organization_id,
        )
    except Exception as exc:
        logger.exception(
            "VectorDB.similarity_search_detailed_failed | knowledge_base_id={kb_id} error={error}",
            kb_id=knowledge_base_id,
            error=str(exc),
        )
        return []
