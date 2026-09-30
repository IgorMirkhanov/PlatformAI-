"""LLM response cache — Redis exact-match plus a Chroma semantic fallback.

Exact-match keys combine ``bot_id``, a prompt-version stamp, and a SHA-256 of the
normalized user utterance. The semantic cache (below) catches near-duplicate
phrasing exact-match misses on — embedding nearest-neighbor search in a
per-bot Chroma collection, gated by the same prompt_version/cache_ver so it
can never surface an answer from before the last prompt edit or invalidation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Final

from loguru import logger

from app.core.config import settings

DEFAULT_LLM_CACHE_TTL_SECONDS: Final[int] = 24 * 60 * 60  # 24 hours
_KEY_PREFIX: Final[str] = "llm:exact"
_VERSION_PREFIX: Final[str] = "llm:ver"


@dataclass(frozen=True)
class CachedLLMResponse:
    """Payload recovered from Redis exact-match cache."""

    text: str
    cache_hit: bool = True
    bot_id: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def normalize_incoming_text(text: str) -> str:
    """Normalize user text for stable exact-match hashing."""
    collapsed = re.sub(r"\s+", " ", (text or "").strip().lower())
    return collapsed


def compute_prompt_version(system_prompt: str) -> str:
    """Short fingerprint of the active system prompt (acts as prompt version)."""
    material = (system_prompt or "").strip().encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


class LLMResponseCacheManager:
    """Redis-backed exact-match LLM response cache with semantic stubs."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        ttl_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._redis_url = redis_url or settings.REDIS_URL
        self._ttl = int(
            ttl_seconds
            if ttl_seconds is not None
            else getattr(settings, "LLM_CACHE_TTL_SECONDS", DEFAULT_LLM_CACHE_TTL_SECONDS)
            or DEFAULT_LLM_CACHE_TTL_SECONDS
        )
        env_enabled = getattr(settings, "LLM_CACHE_ENABLED", True)
        self._enabled = bool(enabled if enabled is not None else env_enabled)
        self._async_client: Any | None = None
        self._bound_loop: asyncio.AbstractEventLoop | None = None

    async def aclose(self) -> None:
        """Drop the cached Redis client (call when the event loop is replaced)."""
        client = self._async_client
        self._async_client = None
        self._bound_loop = None
        if client is None:
            return
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is None:
            return
        with suppress(Exception):
            result = close()
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                await result

    async def _client(self) -> Any:
        loop = asyncio.get_running_loop()
        if self._async_client is not None and self._bound_loop is not loop:
            await self.aclose()
        if self._async_client is None:
            import redis.asyncio as aioredis

            self._async_client = aioredis.from_url(
                self._redis_url,
                socket_connect_timeout=0.4,
                socket_timeout=0.6,
                decode_responses=True,
                max_connections=50,
            )
            self._bound_loop = loop
        return self._async_client

    def _version_key(self, bot_id: uuid.UUID | str) -> str:
        return f"{_VERSION_PREFIX}:{bot_id}"

    async def get_bot_cache_version(self, bot_id: uuid.UUID | str) -> str:
        """Monotonic version stamp; bumps on ``invalidate_bot_cache``."""
        if not self._enabled:
            return "0"
        try:
            client = await self._client()
            value = await client.get(self._version_key(bot_id))
            return str(value or "0")
        except Exception as exc:
            logger.warning(
                "LLMCache.version_read_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            return "0"

    async def build_exact_cache_key(
        self,
        *,
        bot_id: uuid.UUID | str,
        system_prompt: str,
        incoming_text: str,
        model_name: str | None = None,
        temperature: float | None = None,
        prompt_version: str | None = None,
        organization_id: uuid.UUID | str | None = None,
        client_id: uuid.UUID | str | None = None,
    ) -> str:
        version = prompt_version or compute_prompt_version(system_prompt)
        cache_ver = await self.get_bot_cache_version(bot_id)
        normalized = normalize_incoming_text(incoming_text)
        material = "|".join(
            [
                str(organization_id or ""),
                str(bot_id),
                str(client_id or ""),
                cache_ver,
                version,
                (model_name or "").strip().lower(),
                f"{float(temperature):.4f}" if temperature is not None else "",
                normalized,
            ]
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return f"{_KEY_PREFIX}:{bot_id}:{cache_ver}:{digest}"

    async def get_cached_response(
        self,
        *,
        bot_id: uuid.UUID | str | None,
        system_prompt: str,
        incoming_text: str,
        model_name: str | None = None,
        temperature: float | None = None,
    ) -> CachedLLMResponse | None:
        """Exact-match lookup. Returns ``None`` on miss or Redis failures (never raises)."""
        if not self._enabled or bot_id is None:
            return None

        key = await self.build_exact_cache_key(
            bot_id=bot_id,
            system_prompt=system_prompt,
            incoming_text=incoming_text,
            model_name=model_name,
            temperature=temperature,
        )
        try:
            client = await self._client()
            raw = await client.get(key)
        except Exception as exc:
            logger.warning(
                "LLMCache.get_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            return None

        if not raw:
            self._record_lookup("exact", hit=False)
            return None

        try:
            payload = json.loads(raw)
            text = str(payload.get("text") or "").strip()
            if not text:
                self._record_lookup("exact", hit=False)
                return None
            self._record_lookup("exact", hit=True)
            return CachedLLMResponse(
                text=text,
                cache_hit=True,
                bot_id=str(bot_id),
                model_name=payload.get("model_name"),
                prompt_version=payload.get("prompt_version"),
                input_tokens=int(payload.get("input_tokens") or 0),
                output_tokens=int(payload.get("output_tokens") or 0),
                total_tokens=int(payload.get("total_tokens") or 0),
            )
        except Exception as exc:
            logger.warning(
                "LLMCache.decode_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            self._record_lookup("exact", hit=False)
            return None

    @staticmethod
    def _record_lookup(cache_type: str, *, hit: bool) -> None:
        try:
            from app.core.metrics import record_llm_cache_lookup

            record_llm_cache_lookup(cache_type, hit=hit)
        except Exception:  # noqa: BLE001 — metrics must never break the cache path
            pass

    async def set_cached_response(
        self,
        *,
        bot_id: uuid.UUID | str | None,
        system_prompt: str,
        incoming_text: str,
        response_text: str,
        model_name: str | None = None,
        temperature: float | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Persist a successful completion. Failures are logged and swallowed."""
        if not self._enabled or bot_id is None:
            return False
        text = (response_text or "").strip()
        if not text:
            return False

        prompt_version = compute_prompt_version(system_prompt)
        key = await self.build_exact_cache_key(
            bot_id=bot_id,
            system_prompt=system_prompt,
            incoming_text=incoming_text,
            model_name=model_name,
            temperature=temperature,
            prompt_version=prompt_version,
        )
        payload = {
            "text": text,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "total_tokens": int(total_tokens or 0),
            "cache_hit": False,
        }
        ttl = int(ttl_seconds if ttl_seconds is not None else self._ttl)

        try:
            client = await self._client()
            await client.setex(key, ttl, json.dumps(payload, ensure_ascii=False))
            logger.debug(
                "LLMCache.set | bot_id={bot_id} key={key} ttl={ttl}",
                bot_id=bot_id,
                key=key,
                ttl=ttl,
            )
            return True
        except Exception as exc:
            logger.warning(
                "LLMCache.set_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            return False

    async def invalidate_bot_cache(self, bot_id: uuid.UUID | str) -> int:
        """Purge exact-match entries for a bot and bump the version stamp.

        Called when prompting / RAG knowledge changes so stale answers cannot leak.
        """
        deleted = 0
        if not self._enabled:
            return 0

        try:
            client = await self._client()
            # Bump version so existing keys become unreachable even if SCAN is partial.
            await client.incr(self._version_key(bot_id))
            pattern = f"{_KEY_PREFIX}:{bot_id}:*"
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    deleted += int(await client.delete(*keys))
                if cursor == 0:
                    break
            logger.info(
                "LLMCache.invalidate_bot | bot_id={bot_id} deleted={deleted}",
                bot_id=bot_id,
                deleted=deleted,
            )
        except Exception as exc:
            logger.warning(
                "LLMCache.invalidate_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )

        try:
            from app.core.vector_db import purge_semantic_cache

            await purge_semantic_cache(bot_id)
        except Exception as exc:
            # The bumped cache_ver already makes old semantic entries
            # unreachable (queries filter on it) even if this best-effort
            # cleanup fails — never let a Chroma outage break invalidation.
            logger.warning(
                "LLMCache.semantic_purge_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
        return deleted

    # ------------------------------------------------------------------
    # Semantic cache — Chroma nearest-neighbor lookup against past turns,
    # scoped to the bot's current prompt_version + cache_ver so a prompt
    # edit or invalidate_bot_cache() call can never surface a stale answer.
    # ------------------------------------------------------------------

    async def get_semantic_cached_response(
        self,
        *,
        bot_id: uuid.UUID | str | None,
        system_prompt: str,
        incoming_text: str,
        model_name: str | None = None,
        similarity_threshold: float | None = None,
    ) -> CachedLLMResponse | None:
        """Nearest-neighbor lookup against this bot's past turns.

        Filtered to the bot's current ``cache_ver`` + ``prompt_version`` +
        ``model_name`` so a prompt edit, an ``invalidate_bot_cache()`` call,
        or a model switch can never surface a stale or cross-model answer —
        only the similarity match itself is fuzzy. Never raises; a Chroma or
        embedding-provider failure degrades to a miss, same as a Redis outage
        does for the exact-match cache.
        """
        if not self._enabled or bot_id is None:
            return None
        text = normalize_incoming_text(incoming_text)
        if not text:
            return None

        threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else float(getattr(settings, "LLM_SEMANTIC_CACHE_THRESHOLD", 0.92))
        )
        prompt_version = compute_prompt_version(system_prompt)
        cache_ver = await self.get_bot_cache_version(bot_id)
        resolved_model = (model_name or "").strip().lower()

        try:
            from app.core.embeddings import embed_text
            from app.core.vector_db import query_semantic_cache

            embedding = await embed_text(text)
            hit = await query_semantic_cache(
                str(bot_id),
                embedding,
                prompt_version=prompt_version,
                cache_ver=cache_ver,
                model_name=resolved_model,
            )
        except Exception as exc:
            logger.warning(
                "LLMCache.semantic_get_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            self._record_lookup("semantic", hit=False)
            return None

        if hit is None or hit["similarity"] < threshold:
            self._record_lookup("semantic", hit=False)
            return None

        meta = hit["metadata"]
        response_text = str(meta.get("response_text") or "").strip()
        if not response_text:
            self._record_lookup("semantic", hit=False)
            return None

        self._record_lookup("semantic", hit=True)
        logger.debug(
            "LLMCache.semantic_hit | bot_id={bot_id} similarity={similarity}",
            bot_id=bot_id,
            similarity=round(hit["similarity"], 4),
        )
        return CachedLLMResponse(
            text=response_text,
            cache_hit=True,
            bot_id=str(bot_id),
            model_name=str(meta.get("model_name") or "") or None,
            prompt_version=str(meta.get("prompt_version") or "") or None,
            input_tokens=int(meta.get("input_tokens") or 0),
            output_tokens=int(meta.get("output_tokens") or 0),
            total_tokens=int(meta.get("total_tokens") or 0),
        )

    async def register_semantic_turn(
        self,
        *,
        bot_id: uuid.UUID | str | None,
        system_prompt: str,
        incoming_text: str,
        response_text: str,
        model_name: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        embedding: list[float] | None = None,
    ) -> bool:
        """Store a conversational turn for future semantic short-circuit."""
        if not self._enabled or bot_id is None:
            return False
        text = normalize_incoming_text(incoming_text)
        response = (response_text or "").strip()
        if not text or not response:
            return False

        prompt_version = compute_prompt_version(system_prompt)
        cache_ver = await self.get_bot_cache_version(bot_id)
        resolved_model = (model_name or "").strip().lower()

        try:
            if embedding is None:
                from app.core.embeddings import embed_text

                embedding = await embed_text(text)
            from app.core.vector_db import upsert_semantic_cache_entry

            entry_id = hashlib.sha256(
                "|".join([str(bot_id), cache_ver, prompt_version, resolved_model, text]).encode(
                    "utf-8"
                )
            ).hexdigest()
            await upsert_semantic_cache_entry(
                str(bot_id),
                entry_id,
                embedding,
                text,
                {
                    "response_text": response,
                    "model_name": resolved_model,
                    "prompt_version": prompt_version,
                    "cache_ver": cache_ver,
                    "input_tokens": int(input_tokens or 0),
                    "output_tokens": int(output_tokens or 0),
                    "total_tokens": int(total_tokens or 0),
                },
            )
            return True
        except Exception as exc:
            logger.warning(
                "LLMCache.semantic_register_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            return False


llm_response_cache = LLMResponseCacheManager()
