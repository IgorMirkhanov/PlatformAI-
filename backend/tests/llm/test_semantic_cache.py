"""Semantic LLM cache — threshold gating, prompt/model/cache_ver scoping, invalidation.

Chroma and the embedding provider are mocked (see tests/test_vector_db.py for
the Chroma-facing sync functions); these tests cover LLMResponseCacheManager's
own decision logic. Uses the real local Redis for cache_ver bookkeeping, same
as the rest of the exact-match cache's tests.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.llm_cache import LLMResponseCacheManager, compute_prompt_version


@pytest.fixture
def cache() -> LLMResponseCacheManager:
    return LLMResponseCacheManager()


def _bot_id() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_semantic_get_returns_none_when_disabled() -> None:
    cache = LLMResponseCacheManager(enabled=False)
    result = await cache.get_semantic_cached_response(
        bot_id=_bot_id(), system_prompt="sp", incoming_text="hello"
    )
    assert result is None


@pytest.mark.asyncio
async def test_semantic_get_returns_none_for_missing_bot_id(
    cache: LLMResponseCacheManager,
) -> None:
    result = await cache.get_semantic_cached_response(
        bot_id=None, system_prompt="sp", incoming_text="hello"
    )
    assert result is None


@pytest.mark.asyncio
async def test_semantic_get_hit_above_threshold(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    bot_id = _bot_id()
    monkeypatch.setattr("app.core.embeddings.embed_text", AsyncMock(return_value=[0.1, 0.2]))
    monkeypatch.setattr(
        "app.core.vector_db.query_semantic_cache",
        AsyncMock(
            return_value={
                "similarity": 0.95,
                "text": "normalized query",
                "metadata": {
                    "response_text": "Мы работаем с 9 до 18.",
                    "model_name": "gpt-4o-mini",
                    "prompt_version": "abc",
                    "input_tokens": 20,
                    "output_tokens": 10,
                    "total_tokens": 30,
                },
            }
        ),
    )

    result = await cache.get_semantic_cached_response(
        bot_id=bot_id,
        system_prompt="You are helpful.",
        incoming_text="Во сколько вы открываетесь?",
        model_name="gpt-4o-mini",
    )

    assert result is not None
    assert result.text == "Мы работаем с 9 до 18."
    assert result.total_tokens == 30


@pytest.mark.asyncio
async def test_semantic_get_miss_below_threshold(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    monkeypatch.setattr("app.core.embeddings.embed_text", AsyncMock(return_value=[0.1, 0.2]))
    monkeypatch.setattr(
        "app.core.vector_db.query_semantic_cache",
        AsyncMock(
            return_value={
                "similarity": 0.5,
                "text": "unrelated",
                "metadata": {"response_text": "irrelevant answer"},
            }
        ),
    )

    result = await cache.get_semantic_cached_response(
        bot_id=_bot_id(),
        system_prompt="You are helpful.",
        incoming_text="Расскажи рецепт борща",
        similarity_threshold=0.92,
    )

    assert result is None


@pytest.mark.asyncio
async def test_semantic_get_custom_threshold_is_respected(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    monkeypatch.setattr("app.core.embeddings.embed_text", AsyncMock(return_value=[0.1, 0.2]))
    monkeypatch.setattr(
        "app.core.vector_db.query_semantic_cache",
        AsyncMock(
            return_value={
                "similarity": 0.8,
                "text": "close enough",
                "metadata": {"response_text": "answer"},
            }
        ),
    )

    # Below the default 0.92 threshold but above a caller-supplied 0.75.
    result = await cache.get_semantic_cached_response(
        bot_id=_bot_id(),
        system_prompt="sp",
        incoming_text="text",
        similarity_threshold=0.75,
    )
    assert result is not None
    assert result.text == "answer"


@pytest.mark.asyncio
async def test_semantic_get_returns_none_on_vector_db_error(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    monkeypatch.setattr("app.core.embeddings.embed_text", AsyncMock(return_value=[0.1]))
    monkeypatch.setattr(
        "app.core.vector_db.query_semantic_cache",
        AsyncMock(side_effect=RuntimeError("chroma unreachable")),
    )

    result = await cache.get_semantic_cached_response(
        bot_id=_bot_id(), system_prompt="sp", incoming_text="hello"
    )
    assert result is None  # never raises — degrades to a miss


@pytest.mark.asyncio
async def test_semantic_register_writes_normalized_text_and_metadata(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    bot_id = _bot_id()
    monkeypatch.setattr("app.core.embeddings.embed_text", AsyncMock(return_value=[0.1, 0.2]))
    upsert_mock = AsyncMock()
    monkeypatch.setattr("app.core.vector_db.upsert_semantic_cache_entry", upsert_mock)

    ok = await cache.register_semantic_turn(
        bot_id=bot_id,
        system_prompt="You are helpful.",
        incoming_text="  Здравствуйте,  Какой у вас режим работы?  ",
        response_text="Мы работаем с 9 до 18.",
        model_name="GPT-4o-Mini",
        input_tokens=20,
        output_tokens=10,
        total_tokens=30,
    )

    assert ok is True
    upsert_mock.assert_awaited_once()
    args = upsert_mock.await_args.args
    assert args[0] == bot_id
    assert isinstance(args[1], str) and args[1]  # entry_id
    assert args[2] == [0.1, 0.2]  # embedding
    assert args[3] == "здравствуйте, какой у вас режим работы?"  # normalized text
    metadata = args[4]
    assert metadata["response_text"] == "Мы работаем с 9 до 18."
    assert metadata["model_name"] == "gpt-4o-mini"  # lowercased
    assert metadata["total_tokens"] == 30


@pytest.mark.asyncio
async def test_semantic_register_rejects_empty_text_or_response(
    cache: LLMResponseCacheManager,
) -> None:
    assert (
        await cache.register_semantic_turn(
            bot_id=_bot_id(), system_prompt="sp", incoming_text="   ", response_text="answer"
        )
        is False
    )
    assert (
        await cache.register_semantic_turn(
            bot_id=_bot_id(), system_prompt="sp", incoming_text="hello", response_text=""
        )
        is False
    )


@pytest.mark.asyncio
async def test_semantic_register_returns_false_on_vector_db_error(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    monkeypatch.setattr("app.core.embeddings.embed_text", AsyncMock(return_value=[0.1]))
    monkeypatch.setattr(
        "app.core.vector_db.upsert_semantic_cache_entry",
        AsyncMock(side_effect=RuntimeError("chroma unreachable")),
    )

    ok = await cache.register_semantic_turn(
        bot_id=_bot_id(), system_prompt="sp", incoming_text="hello", response_text="answer"
    )
    assert ok is False  # never raises


@pytest.mark.asyncio
async def test_invalidate_bot_cache_purges_semantic_collection(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    bot_id = _bot_id()
    purge_mock = AsyncMock()
    monkeypatch.setattr("app.core.vector_db.purge_semantic_cache", purge_mock)

    await cache.invalidate_bot_cache(bot_id)

    purge_mock.assert_awaited_once_with(bot_id)


@pytest.mark.asyncio
async def test_invalidate_survives_semantic_purge_failure(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    bot_id = _bot_id()
    monkeypatch.setattr(
        "app.core.vector_db.purge_semantic_cache",
        AsyncMock(side_effect=RuntimeError("chroma unreachable")),
    )

    # Must not raise even though the best-effort Chroma purge fails.
    deleted = await cache.invalidate_bot_cache(bot_id)
    assert isinstance(deleted, int)


@pytest.mark.asyncio
async def test_semantic_lookups_record_cache_metrics(
    monkeypatch: pytest.MonkeyPatch, cache: LLMResponseCacheManager
) -> None:
    from app.core import metrics

    monkeypatch.setattr("app.core.embeddings.embed_text", AsyncMock(return_value=[0.1]))
    monkeypatch.setattr(
        "app.core.vector_db.query_semantic_cache",
        AsyncMock(return_value=None),
    )
    record_spy = []
    monkeypatch.setattr(
        metrics,
        "record_llm_cache_lookup",
        lambda cache_type, hit: record_spy.append((cache_type, hit)),
    )

    await cache.get_semantic_cached_response(
        bot_id=_bot_id(), system_prompt="sp", incoming_text="hello"
    )

    assert ("semantic", False) in record_spy


def test_compute_prompt_version_is_stable_for_same_prompt() -> None:
    assert compute_prompt_version("system prompt") == compute_prompt_version("system prompt")
    assert compute_prompt_version("prompt a") != compute_prompt_version("prompt b")
