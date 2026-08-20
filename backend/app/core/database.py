"""SQLAlchemy Base + re-exports of the shared async engine/session."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.db.session import (
    DBSessionMiddleware,
    async_session_factory,
    engine,
    get_db,
    run_celery_async,
)

__all__ = [
    "Base",
    "DBSessionMiddleware",
    "async_session_factory",
    "engine",
    "get_db",
    "run_celery_async",
    "AsyncSession",
    "AsyncGenerator",
]


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""
