from __future__ import annotations

import asyncio
import hashlib
import struct
from typing import TYPE_CHECKING

from loguru import logger

from app.core.config import settings

if TYPE_CHECKING:
    pass

EMBEDDING_DIMENSION = 384


def _hash_embed_text(text: str, dimensions: int = EMBEDDING_DIMENSION) -> list[float]:
    """Deterministic lightweight fallback embedding for local/dev usage."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    seed = digest

    while len(values) < dimensions:
        seed = hashlib.sha256(seed).digest()
        for index in range(0, len(seed), 4):
            if len(values) >= dimensions:
                break
            chunk = seed[index : index + 4]
            if len(chunk) < 4:
                continue
            integer = struct.unpack("!I", chunk)[0]
            values.append((integer / 2**32) * 2 - 1)

    norm = sum(value * value for value in values) ** 0.5 or 1.0
    return [value / norm for value in values]


async def _openai_embed_texts(texts: list[str]) -> list[list[float]]:
    from openai import AsyncOpenAI

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    logger.debug("Embeddings.openai | count={count}", count=len(texts))

    response = await client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def _sentence_transformer_embed_texts(texts: list[str]) -> list[list[float]]:
    def _encode() -> list[list[float]]:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        vectors = model.encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    logger.debug("Embeddings.sentence_transformers | count={count}", count=len(texts))
    return await asyncio.to_thread(_encode)


async def _openrouter_embed_texts(texts: list[str]) -> list[list[float]]:
    from openai import AsyncOpenAI

    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=(settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1").rstrip("/"),
    )
    logger.debug("Embeddings.openrouter | count={count}", count=len(texts))
    response = await client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using the best available configured provider."""
    if not texts:
        return []

    provider = settings.EMBEDDING_PROVIDER.lower()

    if provider in {"auto", "openai"} and settings.OPENAI_API_KEY:
        try:
            return await _openai_embed_texts(texts)
        except Exception as exc:
            logger.warning("Embeddings.openai_failed | error={error}", error=str(exc))
            if provider == "openai":
                raise

    if provider in {"auto", "openrouter"} and settings.OPENROUTER_API_KEY:
        try:
            return await _openrouter_embed_texts(texts)
        except Exception as exc:
            logger.warning("Embeddings.openrouter_failed | error={error}", error=str(exc))
            if provider == "openrouter":
                raise

    try:
        return await _sentence_transformer_embed_texts(texts)
    except Exception as exc:
        logger.warning(
            "Embeddings.sentence_transformers_unavailable | error={error} — using hash fallback",
            error=str(exc),
        )

    return await asyncio.to_thread(lambda: [_hash_embed_text(text) for text in texts])


async def embed_text(text: str) -> list[float]:
    """Generate a single embedding vector."""
    vectors = await embed_texts([text])
    return vectors[0]
