"""In-memory + Redis-backed cache for active LLM models."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

from loguru import logger

from app.core.config import settings
from app.services.llm.pricing import CreditModelPrice, normalize_model_name

_REDIS_KEY = "llm:models:active:v1"
_CACHE_TTL_SECONDS = 60

_model_cache_by_name: dict[str, "CachedLLMModel"] = {}
_cache_expires_at: float = 0.0


@dataclass(frozen=True, slots=True)
class CachedLLMModel:
    id: str
    provider: str
    model_name: str
    display_name: str
    base_url: str | None
    context_window: int
    cost_per_1k_input: Decimal
    cost_per_1k_output: Decimal
    is_active: bool
    is_system_default: bool

    @classmethod
    def from_row(cls, row: Any) -> CachedLLMModel:
        return cls(
            id=str(row.id),
            provider=str(row.provider).lower(),
            model_name=str(row.model_name),
            display_name=str(row.display_name),
            base_url=getattr(row, "base_url", None),
            context_window=int(row.context_window or 128_000),
            cost_per_1k_input=Decimal(str(row.cost_per_1k_input)),
            cost_per_1k_output=Decimal(str(row.cost_per_1k_output)),
            is_active=bool(row.is_active),
            is_system_default=bool(row.is_system_default),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "model_name": self.model_name,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "context_window": self.context_window,
            "cost_per_1k_input": str(self.cost_per_1k_input),
            "cost_per_1k_output": str(self.cost_per_1k_output),
            "is_active": self.is_active,
            "is_system_default": self.is_system_default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedLLMModel:
        return cls(
            id=str(data["id"]),
            provider=str(data["provider"]).lower(),
            model_name=str(data["model_name"]),
            display_name=str(data["display_name"]),
            base_url=data.get("base_url"),
            context_window=int(data.get("context_window") or 128_000),
            cost_per_1k_input=Decimal(str(data.get("cost_per_1k_input", "10"))),
            cost_per_1k_output=Decimal(str(data.get("cost_per_1k_output", "30"))),
            is_active=bool(data.get("is_active", True)),
            is_system_default=bool(data.get("is_system_default", False)),
        )


def _apply_cache(models: list[CachedLLMModel]) -> None:
    global _cache_expires_at
    _model_cache_by_name.clear()
    for item in models:
        _model_cache_by_name[normalize_model_name(item.model_name)] = item
        _model_cache_by_name[item.model_name.lower()] = item
    _cache_expires_at = time.monotonic() + _CACHE_TTL_SECONDS


def invalidate_model_cache() -> None:
    global _cache_expires_at
    _model_cache_by_name.clear()
    _cache_expires_at = 0.0


def get_cached_model(model_name: str | None) -> CachedLLMModel | None:
    if not model_name:
        return None
    key = normalize_model_name(model_name)
    return _model_cache_by_name.get(key) or _model_cache_by_name.get(model_name.lower())


def _credits_per_1k(value: Decimal) -> int:
    """
    Convert a registry tariff into whole platform credits.

    Registry rows may hold fractional USD tariffs (OpenRouter 0.00015 / 1k);
    truncating them to 0 would silently make a paid model free, so anything
    above zero is billed as at least one credit.
    """
    if value is None or value <= 0:
        return 0
    return max(1, int(value.to_integral_value(rounding=ROUND_CEILING)))


def get_cached_credit_price(model_name: str | None) -> CreditModelPrice | None:
    row = get_cached_model(model_name)
    if row is None or not row.is_active:
        return None
    return {
        "prompt_per_1k": _credits_per_1k(row.cost_per_1k_input),
        "completion_per_1k": _credits_per_1k(row.cost_per_1k_output),
    }


def list_cached_models() -> list[CachedLLMModel]:
    seen: set[str] = set()
    out: list[CachedLLMModel] = []
    for item in _model_cache_by_name.values():
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)
    return sorted(out, key=lambda m: (m.provider, m.display_name))


async def _redis_set(models: list[CachedLLMModel]) -> None:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        payload = json.dumps([m.to_dict() for m in models])
        await client.set(_REDIS_KEY, payload, ex=_CACHE_TTL_SECONDS)
        await client.aclose()
    except Exception as exc:
        logger.debug("LLMModelRegistry.redis_set_skipped | error={error}", error=str(exc))


async def _redis_get() -> list[CachedLLMModel] | None:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = await client.get(_REDIS_KEY)
        await client.aclose()
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, list):
            return None
        return [CachedLLMModel.from_dict(item) for item in data]
    except Exception as exc:
        logger.debug("LLMModelRegistry.redis_get_skipped | error={error}", error=str(exc))
        return None


async def refresh_model_cache_from_db(db) -> list[CachedLLMModel]:
    """Load active models from PostgreSQL into process + Redis cache."""
    from sqlalchemy import select

    from app.models.llm_model import LLMModel

    rows = (
        await db.execute(
            select(LLMModel)
            .where(LLMModel.is_active.is_(True))
            .order_by(LLMModel.provider.asc(), LLMModel.display_name.asc())
        )
    ).scalars().all()
    models = [CachedLLMModel.from_row(row) for row in rows]
    _apply_cache(models)
    await _redis_set(models)
    return models


async def ensure_model_cache(db) -> list[CachedLLMModel]:
    if _model_cache_by_name and time.monotonic() < _cache_expires_at:
        return list_cached_models()
    redis_models = await _redis_get()
    if redis_models:
        _apply_cache(redis_models)
        return list_cached_models()
    return await refresh_model_cache_from_db(db)
