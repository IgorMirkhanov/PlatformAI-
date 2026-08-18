"""Apply SQL migrations 009 + 010 against the local Postgres database."""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ROOT / "migrations" / "009_manual_deposits_and_notifications.sql",
    ROOT / "migrations" / "010_user_is_superadmin.sql",
]
DSN = "postgresql://postgres:postgres@127.0.0.1:5432/mpai"


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        for path in MIGRATIONS:
            await conn.execute(path.read_text(encoding="utf-8"))
            print(f"Applied {path.name}")

        cols = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE (table_name = 'billing_transactions' AND column_name IN ('organization_id', 'receipt_url'))
               OR (table_name = 'users' AND column_name = 'is_superadmin')
            ORDER BY table_name, column_name
            """
        )
        print("verified columns:", [row["column_name"] for row in cols])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
