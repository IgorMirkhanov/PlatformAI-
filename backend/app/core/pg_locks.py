"""PostgreSQL advisory transaction locks for quota / wallet serialization."""

from __future__ import annotations

import inspect
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def pg_advisory_xact_lock_uuid(db: AsyncSession, namespace: int, key: uuid.UUID) -> None:
    """Serialize concurrent work for ``key`` within the current DB transaction."""
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if inspect.isawaitable(bind):
        return
    if bind is None:
        return
    dialect = getattr(bind, "dialect", None)
    if dialect is None or getattr(dialect, "name", None) != "postgresql":
        return
    hi = namespace & 0x7FFFFFFF
    lo = ((key.int >> 64) ^ key.int) & 0x7FFFFFFF
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:hi, :lo)"),
        {"hi": hi, "lo": lo},
    )


# Separate namespaces so wallet and quota locks never collide.
LOCK_NS_WALLET = 71_001
LOCK_NS_QUOTA = 71_002
