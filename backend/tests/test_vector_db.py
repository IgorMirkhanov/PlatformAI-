"""Tests — Chroma SDK stays off the FastAPI event loop via asyncio.to_thread."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import vector_db


@pytest.mark.parametrize(
    "async_fn",
    [
        vector_db.add_chunks_to_bot_collection,
        vector_db.embed_and_store_document,
        vector_db.delete_document_vectors,
        vector_db.purge_bot_vectors,
        vector_db.list_document_chunks,
        vector_db.similarity_search,
        vector_db.similarity_search_detailed,
        vector_db.query_semantic_cache,
        vector_db.upsert_semantic_cache_entry,
        vector_db.purge_semantic_cache,
    ],
)
def test_public_vector_apis_are_async(async_fn: Any) -> None:
    assert inspect.iscoroutinefunction(async_fn)


@pytest.mark.asyncio
async def test_add_chunks_offloads_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    sync_calls: list[tuple[Any, ...]] = []

    def fake_sync(*args: Any, **kwargs: Any) -> int:
        sync_calls.append(args)
        return len(args[3])

    to_thread = AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(vector_db.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(vector_db, "_sync_add_chunks_to_bot_collection", fake_sync)

    count = await vector_db.add_chunks_to_bot_collection(
        bot_id="bot-1",
        document_id="doc-1",
        file_name="faq.txt",
        text_chunks=["hello world", "second chunk"],
        embeddings=[[0.1], [0.2]],
    )

    assert count == 2
    to_thread.assert_awaited()
    assert to_thread.await_args.args[0] is fake_sync
    assert sync_calls, "sync Chroma writer must run via to_thread"


@pytest.mark.asyncio
async def test_delete_document_vectors_offloads_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    to_thread = AsyncMock(return_value=3)
    monkeypatch.setattr(vector_db.asyncio, "to_thread", to_thread)

    removed = await vector_db.delete_document_vectors(
        "doc-1",
        bot_id="bot-1",
        organization_id="org-1",
    )

    assert removed == 3
    to_thread.assert_awaited_once()
    assert to_thread.await_args.args[0] is vector_db._sync_delete_document_vectors


@pytest.mark.asyncio
async def test_list_document_chunks_offloads_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = [{"chunk_index": 0, "text": "a", "similarity_weight": 0.9}]
    to_thread = AsyncMock(return_value=expected)
    monkeypatch.setattr(vector_db.asyncio, "to_thread", to_thread)

    rows = await vector_db.list_document_chunks("doc-1", bot_id="bot-1")

    assert rows == expected
    to_thread.assert_awaited_once()
    assert to_thread.await_args.args[0] is vector_db._sync_list_document_chunks


@pytest.mark.asyncio
async def test_similarity_search_detailed_offloads_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = [
        {
            "text": "hit",
            "similarity_score": 0.9,
            "document_id": "d1",
            "file_name": "a.txt",
            "chunk_index": 0,
            "page_number": None,
            "section": None,
            "source_file_url": None,
            "image_attachment": None,
            "file_url": None,
            "media_url": None,
            "metadata": {},
        }
    ]

    async def fake_embed(_query: str) -> list[float]:
        return [0.1, 0.2]

    to_thread = AsyncMock(return_value=hits)
    monkeypatch.setattr(vector_db, "embed_text", fake_embed)
    monkeypatch.setattr(vector_db.asyncio, "to_thread", to_thread)

    result = await vector_db.similarity_search_detailed("kb-1", "hello", top_k=2)

    assert result == hits
    to_thread.assert_awaited_once()
    assert to_thread.await_args.args[0] is vector_db._sync_query_chunks_detailed


@pytest.mark.asyncio
async def test_sync_add_uses_collection_add(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = MagicMock()
    monkeypatch.setattr(vector_db, "_get_collection", lambda: collection)

    vector_db._sync_add_chunks(
        "kb-1",
        "doc-1",
        "file.txt",
        ["chunk-a"],
        [[0.5]],
        extra_metadata={"organization_id": "org-1"},
    )

    collection.add.assert_called_once()
    kwargs = collection.add.call_args.kwargs
    assert kwargs["ids"] == ["doc-1:0"]
    assert kwargs["documents"] == ["chunk-a"]


@pytest.mark.asyncio
async def test_sync_delete_uses_collection_get_and_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = MagicMock()
    collection.get.return_value = {"ids": ["doc-1:0", "doc-1:1"]}
    monkeypatch.setattr(vector_db, "_get_collection", lambda: collection)
    monkeypatch.setattr(vector_db, "_get_bot_collection", lambda _bot: collection)
    monkeypatch.setattr(vector_db, "_get_org_collection", lambda _org: collection)

    removed = vector_db._sync_delete_document_vectors(
        "doc-1",
        bot_id="bot-1",
        organization_id="org-1",
    )

    assert removed == 6  # shared + bot + org, 2 ids each
    assert collection.get.call_count == 3
    assert collection.delete.call_count == 3


def test_build_rag_where_filter_skips_empty_allowed() -> None:
    assert vector_db.build_rag_where_filter("kb", allowed_document_ids=[]) is None
    clause = vector_db.build_rag_where_filter("kb", excluded_document_ids=["a"])
    assert clause is not None
    assert "$and" in clause


@pytest.mark.asyncio
async def test_event_loop_stays_responsive_during_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While Chroma work runs in a worker thread, the loop can schedule other tasks."""

    def blocking_sync(*_a: Any, **_k: Any) -> int:
        import time

        time.sleep(0.05)
        return 1

    monkeypatch.setattr(vector_db, "_sync_delete_document_vectors", blocking_sync)

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    delete_task = asyncio.create_task(vector_db.delete_document_vectors("doc-1"))
    tick_task = asyncio.create_task(ticker())
    removed, _ = await asyncio.gather(delete_task, tick_task)

    assert removed == 1
    assert ticks >= 3, "event loop should keep ticking while Chroma work is offloaded"


# ---------------------------------------------------------------------------
# Semantic LLM cache — separate per-bot collection from the KB one above.
# ---------------------------------------------------------------------------


def test_semantic_cache_collection_name_is_isolated_from_kb_collection() -> None:
    bot_id = "bot-1"
    assert vector_db.semantic_cache_collection_name(bot_id) != vector_db.bot_collection_name(
        bot_id
    )
    assert vector_db.semantic_cache_collection_name(bot_id) == "semcache_bot_bot-1"


def test_sync_query_semantic_cache_short_circuits_empty_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = MagicMock()
    collection.count.return_value = 0
    monkeypatch.setattr(vector_db, "_get_semantic_cache_collection", lambda _bot_id: collection)

    result = vector_db._sync_query_semantic_cache(
        "bot-1", [0.1, 0.2], prompt_version="pv1", cache_ver="0", model_name="gpt-4o-mini"
    )

    assert result is None
    collection.query.assert_not_called()


def test_sync_query_semantic_cache_filters_by_prompt_cache_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = MagicMock()
    collection.count.return_value = 1
    collection.query.return_value = {
        "documents": [["здравствуйте какой у вас режим работы"]],
        "distances": [[0.1]],
        "metadatas": [[{"response_text": "Мы работаем с 9 до 18.", "model_name": "gpt-4o-mini"}]],
    }
    monkeypatch.setattr(vector_db, "_get_semantic_cache_collection", lambda _bot_id: collection)

    result = vector_db._sync_query_semantic_cache(
        "bot-1",
        [0.1, 0.2],
        prompt_version="pv1",
        cache_ver="3",
        model_name="gpt-4o-mini",
    )

    assert result is not None
    assert result["similarity"] == pytest.approx(0.9)
    assert result["metadata"]["response_text"] == "Мы работаем с 9 до 18."

    where = collection.query.call_args.kwargs["where"]
    assert {"prompt_version": "pv1"} in where["$and"]
    assert {"cache_ver": "3"} in where["$and"]
    assert {"model_name": "gpt-4o-mini"} in where["$and"]


def test_sync_upsert_semantic_cache_entry_writes_document_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = MagicMock()
    monkeypatch.setattr(vector_db, "_get_semantic_cache_collection", lambda _bot_id: collection)

    vector_db._sync_upsert_semantic_cache_entry(
        "bot-1",
        "entry-1",
        [0.1, 0.2],
        "normalized text",
        {"response_text": "answer", "model_name": "gpt-4o-mini"},
    )

    collection.upsert.assert_called_once_with(
        ids=["entry-1"],
        embeddings=[[0.1, 0.2]],
        documents=["normalized text"],
        metadatas=[{"response_text": "answer", "model_name": "gpt-4o-mini"}],
    )


def test_sync_purge_semantic_cache_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.delete_collection.side_effect = Exception("collection does not exist")
    monkeypatch.setattr(vector_db, "_get_chroma_client", lambda: client)

    vector_db._sync_purge_semantic_cache("bot-1")  # must not raise

    client.delete_collection.assert_called_once_with(name="semcache_bot_bot-1")
