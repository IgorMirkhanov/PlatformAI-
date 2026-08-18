"""SQLAlchemy async engine + session factory (connection pool tuned for SaaS)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import suppress

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
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=settings.DB_POOL_RECYCLE,
    connect_args={
        "server_settings": {
            "statement_timeout": "30000",
            "lock_timeout": "10000",
            "idle_in_transaction_session_timeout": "60000",
        }
    },
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
