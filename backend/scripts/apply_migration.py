"""Apply SQL migration files to the local PostgreSQL database."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/mpai"


async def inspect(conn: asyncpg.Connection) -> None:
    cols = await conn.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'users'
        ORDER BY ordinal_position
        """
    )
    print("users columns:", [row["column_name"] for row in cols])
    tables = await conn.fetch(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename IN ('companies', 'user_company_workspaces')
        """
    )
    print("multi-tenant tables:", [row["tablename"] for row in tables])


async def apply_file(conn: asyncpg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    print(f"Applying {path.name} ...")
    await conn.execute(sql)
    print(f"Applied {path.name}")


async def main() -> int:
    migration_names = sys.argv[1:] or ["008_companies_and_workspaces.sql"]
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await inspect(conn)
        for name in migration_names:
            path = MIGRATIONS_DIR / name
            if not path.exists():
                print(f"Missing migration: {path}")
                return 1
            await apply_file(conn, path)
        print("--- after migration ---")
        await inspect(conn)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
