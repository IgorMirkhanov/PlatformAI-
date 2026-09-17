"""SQLAlchemy async engine + session factory (connection pool tuned for SaaS)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import settings

# Shared async engine — pool sized for concurrent tenant traffic.
#
# statement_timeout/lock_timeout/idle_in_transaction_session_timeout are NOT
# set here via asyncpg's server_settings (Postgres startup-packet params)
# anymore — PgBouncer in transaction-pooling mode only forwards a fixed
# whitelist of startup parameters and rejects the rest with "unsupported
# startup parameter" (confirmed against a real PgBouncer instance), which
# broke every request the moment PgBouncer went in front of the API. They are
# instead set as ALTER DATABASE defaults (migration 067_db_session_timeouts)
# — Postgres applies them to every new backend session either way, pooled or
# not.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=settings.DB_POOL_RECYCLE,
    connect_args={"statement_cache_size": 0} if settings.DB_PGBOUNCER_COMPAT else {},
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

_REQUEST_DB_ATTR = "db"


async def _abort_request_db(request: Request) -> None:
    session: AsyncSession | None = getattr(request.state, _REQUEST_DB_ATTR, None)
    if session is None:
        return
    setattr(request.state, _REQUEST_DB_ATTR, None)
    with suppress(Exception):
        await session.rollback()
    with suppress(Exception):
        await session.close()


async def _finalize_request_db(request: Request, status_code: int) -> None:
    """Commit on success; roll back when the HTTP response is an error."""
    session: AsyncSession | None = getattr(request.state, _REQUEST_DB_ATTR, None)
    if session is None:
        return
    setattr(request.state, _REQUEST_DB_ATTR, None)
    error_occurred = bool(getattr(request.state, "error_occurred", False))
    try:
        if error_occurred or status_code >= 400:
            await session.rollback()
        else:
            await session.commit()
    except Exception:
        with suppress(Exception):
            await session.rollback()
        raise
    finally:
        with suppress(Exception):
            await session.close()


class DBSessionMiddleware(BaseHTTPMiddleware):
    """Finalize the request-scoped DB session using the response status code.

    ``get_db`` leaves the session open on the success path so this middleware can
    roll back when endpoints catch errors and return HTTP ≥ 400 (no exception).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        try:
            response = await call_next(request)
        except Exception:
            request.state.error_occurred = True
            await _abort_request_db(request)
            raise
        await _finalize_request_db(request, response.status_code)
        return response


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async database session.

    Uncaught exceptions (including ``HTTPException``) trigger an immediate
    rollback. Successful generator exit does **not** auto-commit —
    ``DBSessionMiddleware`` commits only when the response status is ``< 400``
    and ``request.state.error_occurred`` is unset; otherwise it rolls back.
    """
    from fastapi import HTTPException

    session = async_session_factory()
    setattr(request.state, _REQUEST_DB_ATTR, session)
    try:
        yield session
    except HTTPException:
        request.state.error_occurred = True
        await _abort_request_db(request)
        raise
    except Exception:
        request.state.error_occurred = True
        await _abort_request_db(request)
        raise


# Persistent loop per Celery prefork process. ``asyncio.run`` closes the loop
# after every task, which poisons Redis/httpx clients and SQLAlchemy pools
# ("Event loop is closed" / "Future attached to a different loop").
_celery_loop: asyncio.AbstractEventLoop | None = None


async def _dispose_loop_bound_resources() -> None:
    """Drop engine pools and cached async clients bound to a dead loop."""
    with suppress(Exception):
        await engine.dispose()
    with suppress(Exception):
        from app.core.llm_cache import llm_response_cache

        await llm_response_cache.aclose()
    with suppress(Exception):
        from app.services.llm.client import aclose_cached_openai_clients

        await aclose_cached_openai_clients()


def reset_celery_async_state() -> None:
    """Reset loop-bound state after Celery fork (or a poisoned loop)."""
    global _celery_loop
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_dispose_loop_bound_resources())
    except Exception:
        pass
    finally:
        with suppress(Exception):
            loop.close()
    if _celery_loop is not None and not _celery_loop.is_closed():
        with suppress(Exception):
            _celery_loop.close()
    _celery_loop = None
    with suppress(Exception):
        asyncio.set_event_loop(None)


def run_celery_async(coro: Any) -> Any:
    """Run an async coroutine from a Celery prefork worker on a reused loop."""
    global _celery_loop

    loop = _celery_loop
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _celery_loop = loop

    return loop.run_until_complete(coro)
