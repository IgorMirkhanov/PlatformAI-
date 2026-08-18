"""Grant platform Superadmin privileges to a user by email.

Usage (from ``backend/`` or repo root):

    python scripts/make_superadmin.py --email user@example.com

Sets ``is_superadmin=True`` in PostgreSQL (JWT claims refresh on next login).
Requires DATABASE_URL from the environment (same as the API).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if _BACKEND_ROOT.name != "backend":
    candidate = Path(__file__).resolve().parents[1] / "backend"
    if (candidate / "app").is_dir():
        _BACKEND_ROOT = candidate
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session_factory, engine  # noqa: E402
from app.models.users import User  # noqa: E402


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

            user.is_superadmin = True
            user.is_support = False
            if hasattr(user, "is_active"):
                user.is_active = True
            await session.commit()
            print(
                f"[OK] Granted Superadmin (is_superadmin=True) to {user.email} (id={user.id})."
            )
            print("[NOTE] Log out and log in again so the JWT / admin cookie refresh.")
            return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grant is_superadmin to a user by email.",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Account email to promote (e.g. igor.mirkhanov@mail.ru)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(promote(args.email)))


if __name__ == "__main__":
    main()
