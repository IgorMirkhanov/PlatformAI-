"""High-performance LLM response cache backed by Redis.

Exact-match keys combine ``bot_id``, a prompt-version stamp, and a SHA-256 of the
normalized user utterance. Semantic hooks are stubbed for a future embedding index.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Final

from loguru import logger

from app.core.config import settings

DEFAULT_LLM_CACHE_TTL_SECONDS: Final[int] = 24 * 60 * 60  # 24 hours
_KEY_PREFIX: Final[str] = "llm:exact"
_VERSION_PREFIX: Final[str] = "llm:ver"
_SEMANTIC_PREFIX: Final[str] = "llm:semantic"


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

    async def _client(self) -> Any:
        if self._async_client is None:
            import redis.asyncio as aioredis

            self._async_client = aioredis.from_url(
                self._redis_url,
                socket_connect_timeout=0.4,
                socket_timeout=0.6,
                decode_responses=True,
                max_connections=50,
            )
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
            return None

        try:
            payload = json.loads(raw)
            text = str(payload.get("text") or "").strip()
            if not text:
                return None
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
            return None

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
            # Semantic registry stubs (future embeddings).
            sem_pattern = f"{_SEMANTIC_PREFIX}:{bot_id}:*"
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, match=sem_pattern, count=200)
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
        return deleted

    # ------------------------------------------------------------------
    # Semantic match stubs (optional future embedding short-circuit)
    # ------------------------------------------------------------------

    async def get_semantic_cached_response(
        self,
        *,
        bot_id: uuid.UUID | str | None,
        incoming_text: str,
        similarity_threshold: float = 0.92,
    ) -> CachedLLMResponse | None:
        """Stub: semantic nearest-neighbor lookup against recent turn embeddings."""
        _ = (bot_id, incoming_text, similarity_threshold)
        logger.debug("LLMCache.semantic_stub_miss | reason=not_implemented")
        return None

    async def register_semantic_turn(
        self,
        *,
        bot_id: uuid.UUID | str | None,
        incoming_text: str,
        response_text: str,
        embedding: list[float] | None = None,
    ) -> bool:
        """Stub: register a conversational turn embedding for semantic short-circuit."""
        _ = (bot_id, incoming_text, response_text, embedding)
        return False


llm_response_cache = LLMResponseCacheManager()
