"""Pre-release smoke tests — infrastructure + critical registries.

Run::

    pytest backend/tests/smoke/test_system_health.py -v

Infrastructure checks talk to real PostgreSQL / Redis when available and
``pytest.skip`` cleanly when the dependency is down. Registry checks are
pure in-process assertions (no vendor API calls).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Expected registry inventories (release gate)
# ---------------------------------------------------------------------------

EXPECTED_LLM_BACKENDS = (
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "glm",
    "qwen",
    "ollama",
)
EXPECTED_MEDIA_PROVIDERS = ("kling", "nanobanana")
EXPECTED_FLOW_NODE_TYPES = (
    "trigger",
    "condition",
    "llm",
    "api_request",
    "crm_action",
    "google_sheets",
    "sql_query",
    "image_generation",
)


@pytest.fixture
async def smoke_engine() -> AsyncIterator[AsyncEngine]:
    """Per-test engine bound to the current asyncio loop (avoids loop-reuse bugs)."""
    from app.core.config import settings

    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 1. PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_connection_select_one(smoke_engine: AsyncEngine) -> None:
    """Async engine answers ``SELECT 1``."""
    try:
        async with smoke_engine.connect() as conn:
            value = await conn.scalar(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    assert value == 1


@pytest.mark.asyncio
async def test_postgres_session_factory_select_one(smoke_engine: AsyncEngine) -> None:
    """Session factory over the smoke engine can open a short-lived session."""
    factory = async_sessionmaker(
        bind=smoke_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    try:
        async with factory() as session:
            value = await session.scalar(text("SELECT 1"))
            await session.rollback()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL session factory unavailable: {exc}")

    assert value == 1


# ---------------------------------------------------------------------------
# 2. Redis (Flow sessions / cache)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_async_roundtrip_with_ttl() -> None:
    """Async Redis client can SET / GET / TTL / DELETE a smoke key."""
    from app.core.redis_client import get_async_redis

    key = f"smoke:flow-session:{uuid.uuid4()}"
    ttl_seconds = 30
    client = None
    try:
        client = await get_async_redis()
        await client.ping()
        await client.set(key, "ok", ex=ttl_seconds)
        value = await client.get(key)
        remaining = await client.ttl(key)
        deleted = await client.delete(key)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Redis unavailable: {exc}")
    finally:
        if client is not None:
            try:
                await client.delete(key)
            except Exception:
                pass
            close = getattr(client, "aclose", None) or getattr(client, "close", None)
            if close is not None:
                try:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    pass

    assert value == "ok"
    assert isinstance(remaining, int)
    assert 0 < remaining <= ttl_seconds
    assert int(deleted) >= 1


# ---------------------------------------------------------------------------
# 3. LLM Gateway registry
# ---------------------------------------------------------------------------


def test_llm_gateway_registry_contains_expected_backends() -> None:
    """Factory is populated with openai / anthropic / gemini / ollama."""
    import app.services.llm.providers  # noqa: F401 — side-effect registration

    from app.services.llm.factory import LLMProviderFactory

    available = set(LLMProviderFactory.available())
    assert available, "LLMProviderFactory registry is empty"

    missing = [name for name in EXPECTED_LLM_BACKENDS if name not in available]
    assert not missing, (
        f"LLM registry missing backends: {missing}; available={sorted(available)}"
    )

    for name in EXPECTED_LLM_BACKENDS:
        provider = LLMProviderFactory.create(name)
        assert provider is not None
        assert getattr(provider, "provider_id", name) == name


# ---------------------------------------------------------------------------
# 4. Media registry (image generation)
# ---------------------------------------------------------------------------


def test_media_registry_contains_kling_and_nanobanana() -> None:
    """Media connectors for Kling AI and Nano Banana Pro are registered."""
    import app.services.media  # noqa: F401 — side-effect registration

    from app.services.media.base_media import MediaRegistry

    available = set(MediaRegistry.available())
    missing = [name for name in EXPECTED_MEDIA_PROVIDERS if name not in available]
    assert not missing, (
        f"MediaRegistry missing providers: {missing}; available={sorted(available)}"
    )

    for name in EXPECTED_MEDIA_PROVIDERS:
        connector = MediaRegistry.get_connector(name, api_key="smoke-test-key")
        assert connector is not None
        assert getattr(connector, "provider_id", name) == name


# ---------------------------------------------------------------------------
# 5. Flow Builder node registry
# ---------------------------------------------------------------------------


def test_flow_node_registry_contains_critical_handlers() -> None:
    """Default NodeHandlerRegistry wires every release-critical node type."""
    from app.services.flow.nodes.base import build_default_node_registry

    registry = build_default_node_registry()
    available = set(registry.available())

    missing = [name for name in EXPECTED_FLOW_NODE_TYPES if name not in available]
    assert not missing, (
        f"NodeHandlerRegistry missing types: {missing}; available={sorted(available)}"
    )

    for name in EXPECTED_FLOW_NODE_TYPES:
        handler = registry.get(name)
        assert handler is not None, f"No handler for node type '{name}'"
        assert hasattr(handler, "execute")
