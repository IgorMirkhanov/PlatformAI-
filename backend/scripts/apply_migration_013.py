"""Apply migration 013 (bot_channels omnichannel hub table)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "migrations" / "013_bot_channels_hub.sql"
DSN = "postgresql://postgres:postgres@127.0.0.1:5432/mpai"


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(SQL_PATH.read_text(encoding="utf-8"))
        has_table = await conn.fetchval(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'bot_channels'
            """
        )
        print("migration_013_ok", bool(has_table))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
