"""Apply migration 012 (MESSENGER_API_ERROR diagnostic enum)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "migrations" / "012_messenger_api_error_diagnostic.sql"
DSN = "postgresql://postgres:postgres@127.0.0.1:5432/mpai"


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(SQL_PATH.read_text(encoding="utf-8"))
        has_enum = await conn.fetchval(
            """
            SELECT 1 FROM pg_enum e
            JOIN pg_type t ON t.oid = e.enumtypid
            WHERE t.typname = 'diagnostic_error_type' AND e.enumlabel = 'MESSENGER_API_ERROR'
            """
        )
        print("migration_012_ok", bool(has_enum))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
