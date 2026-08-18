"""Promote demo workspace owner to superadmin for local admin tooling."""

from __future__ import annotations

import asyncio

import asyncpg

DSN = "postgresql://postgres:postgres@127.0.0.1:5432/mpai"


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        updated = await conn.execute(
            """
            UPDATE users
            SET is_superadmin = TRUE
            WHERE email = 'admin@mp.ai'
               OR id = (
                    SELECT id FROM users ORDER BY created_at ASC LIMIT 1
               )
            """
        )
        row = await conn.fetchrow(
            "SELECT id, email, is_superadmin FROM users ORDER BY created_at ASC LIMIT 1"
        )
        print(updated, dict(row) if row else None)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
