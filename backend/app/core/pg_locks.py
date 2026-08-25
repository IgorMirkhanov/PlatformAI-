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
LOCK_NS_CRM_OAUTH = 71_003
LOCK_NS_CRM_CAPTURE = 71_004


def _is_postgres(db: AsyncSession) -> bool:
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        return False
    bind = get_bind()
    if inspect.isawaitable(bind) or bind is None:
        return False
    dialect = getattr(bind, "dialect", None)
    return bool(dialect is not None and getattr(dialect, "name", None) == "postgresql")


async def pg_advisory_xact_lock_hashtext(db: AsyncSession, key: str) -> None:
    """Serialize work for ``key`` via ``pg_advisory_xact_lock(hashtext(key))``.

    amoCRM refresh_token is single-use: two concurrent refreshes with the same
    token permanently lock the account out of OAuth until the user reinstalls.
    """
    if not _is_postgres(db):
        return
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": str(key)},
    )


async def try_advisory_lock(session: AsyncSession, lock_key: int) -> bool:
    """Non-blocking ``pg_try_advisory_lock``. Returns True when this session holds the lock."""
    try:
        result = await session.execute(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": int(lock_key) & 0x7FFFFFFFFFFFFFFF},
        )
        return bool(result.scalar())
    except Exception:
        # Fail closed: pretending we hold the lock would allow parallel OAuth HTTP calls.
        return False


async def advisory_unlock(session: AsyncSession, lock_key: int) -> None:
    try:
        await session.execute(
            text("SELECT pg_advisory_unlock(:key)"),
            {"key": int(lock_key) & 0x7FFFFFFFFFFFFFFF},
        )
    except Exception:
        return


def lock_key_for_credential(credential_id: uuid.UUID) -> int:
    """Stable signed 63-bit key derived from UUID (matches hashtext-style uniqueness)."""
    return ((credential_id.int >> 64) ^ credential_id.int) & 0x7FFFFFFFFFFFFFFF
