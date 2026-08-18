"""Grant platform superadmin privileges to a user by email.

Usage (from ``backend/``):

    python scripts/make_admin.py user@example.com

Requires DATABASE_URL from backend/.env (same as the API).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow ``python scripts/make_admin.py`` from backend/ without PYTHONPATH hacks.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.models.users import User


async def promote(email: str) -> int:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        print(f"[ERROR] Invalid email: {email!r}")
        return 1

    try:
        async with async_session_factory() as session:
            result = await session.execute(select(User).where(User.email.ilike(normalized)))
            user = result.scalar_one_or_none()
            if user is None:
                print(f"[ERROR] User not found: {normalized}")
                return 1

            if bool(user.is_superadmin):
                print(f"[OK] {user.email} is already a superadmin (id={user.id}).")
                return 0

            user.is_superadmin = True
            await session.commit()
            print(f"[OK] Granted is_superadmin=True to {user.email} (id={user.id}).")
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant is_superadmin to a user by email.")
    parser.add_argument("email", help="Account email to promote")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(promote(args.email)))


if __name__ == "__main__":
    main()
