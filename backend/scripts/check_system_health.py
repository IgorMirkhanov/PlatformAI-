#!/usr/bin/env python3
"""MP.AI — lightweight infra health check (PostgreSQL, Redis, ChromaDB).

Loads Settings from the environment (prefer repo-root ``.env.production``).
Does not print secret values.

Usage (from repo root):
    python scripts/check_system_health.py
    python backend/scripts/check_system_health.py

Exit codes:
    0 — Postgres + Redis OK (Chroma warn allowed)
    1 — Postgres or Redis unreachable
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if (_REPO_ROOT / "backend" / "app").is_dir():
    sys.path.insert(0, str(_BACKEND_ROOT))
elif (_REPO_ROOT / "app").is_dir():
    # Invoked as backend/scripts/check_system_health.py
    sys.path.insert(0, str(_REPO_ROOT))
    _BACKEND_ROOT = _REPO_ROOT
    _REPO_ROOT = _REPO_ROOT.parent

# Prefer production env for release checks.
for candidate in (
    _REPO_ROOT / ".env.production",
    _BACKEND_ROOT / ".env.production",
    _REPO_ROOT / ".env",
):
    if candidate.is_file():
        try:
            from dotenv import load_dotenv

            load_dotenv(candidate, override=True)
            print(f"[env] loaded {candidate}")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[env] failed to load {candidate}: {exc}")


def _mask_url(url: str) -> str:
    try:
        parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
        host = parsed.hostname or "?"
        port = parsed.port or ""
        db = (parsed.path or "/").lstrip("/") or "?"
        user = parsed.username or "?"
        return f"{parsed.scheme}://{user}:***@{host}:{port}/{db}"
    except Exception:
        return "<unparseable>"


async def check_postgres() -> tuple[bool, str]:
    from app.core.config import settings
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    dsn = settings.DATABASE_URL
    host = getattr(settings, "POSTGRES_SERVER", None) or getattr(settings, "POSTGRES_HOST", None)
    t0 = time.perf_counter()
    engine = create_async_engine(dsn, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(text("SELECT 1"))
            row.scalar_one()
        ms = (time.perf_counter() - t0) * 1000
        return True, f"OK ({ms:.0f}ms) dsn={_mask_url(dsn)} alias_host={host}"
    except Exception as exc:  # noqa: BLE001
        return False, f"FAIL dsn={_mask_url(dsn)} error={type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()


async def check_redis() -> tuple[bool, str]:
    from app.core.config import settings

    url = settings.REDIS_URL
    host = getattr(settings, "REDIS_HOST", None)
    t0 = time.perf_counter()
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(url, socket_connect_timeout=3, decode_responses=True)
        try:
            pong = await client.ping()
            probe_key = "mpai:healthcheck:probe"
            await client.set(probe_key, "1", ex=10)
            val = await client.get(probe_key)
            await client.delete(probe_key)
            ms = (time.perf_counter() - t0) * 1000
            ok = bool(pong) and val == "1"
            return ok, f"{'OK' if ok else 'FAIL'} ({ms:.0f}ms) host={host} ping={pong}"
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        # Sync fallback
        try:
            import redis

            client = redis.Redis.from_url(url, socket_connect_timeout=3)
            pong = client.ping()
            ms = (time.perf_counter() - t0) * 1000
            return bool(pong), f"OK-sync ({ms:.0f}ms) host={host} ping={pong}"
        except Exception as inner:  # noqa: BLE001
            return False, f"FAIL host={host} error={type(inner).__name__}: {inner}"


async def check_chromadb() -> tuple[bool, str]:
    from app.core.config import settings

    host = settings.CHROMADB_HOST or settings.CHROMA_SERVER_HOST or "localhost"
    port = int(settings.CHROMADB_PORT or settings.CHROMA_SERVER_PORT or 8000)
    t0 = time.perf_counter()
    try:
        import httpx

        url = f"http://{host}:{port}/api/v1/heartbeat"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        ms = (time.perf_counter() - t0) * 1000
        if resp.status_code < 500:
            return True, f"OK ({ms:.0f}ms) {host}:{port} status={resp.status_code}"
        return False, f"FAIL ({ms:.0f}ms) {host}:{port} status={resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        # Local/dev may use embedded PersistentClient without HTTP server.
        try:
            from app.core import vector_db as vector_db_mod

            client = vector_db_mod._get_chroma_client()
            _ = client.heartbeat() if hasattr(client, "heartbeat") else True
            ms = (time.perf_counter() - t0) * 1000
            return True, f"OK-embedded ({ms:.0f}ms) host={host}"
        except Exception as inner:  # noqa: BLE001
            return False, (
                f"WARN {host}:{port} unreachable ({type(exc).__name__}); "
                f"embedded fallback failed ({type(inner).__name__}: {inner})"
            )


async def main() -> int:
    from app.core.config import settings

    print("=== MP.AI system health ===")
    print(f"ENVIRONMENT={settings.ENVIRONMENT}")
    print(f"WEBHOOK_BASE_URL={settings.WEBHOOK_BASE_URL}")
    print(settings.format_integration_secrets_audit())
    print("---")

    pg_ok, pg_msg = await check_postgres()
    rd_ok, rd_msg = await check_redis()
    ch_ok, ch_msg = await check_chromadb()

    print(f"PostgreSQL : {'PASS' if pg_ok else 'FAIL'} — {pg_msg}")
    print(f"Redis      : {'PASS' if rd_ok else 'FAIL'} — {rd_msg}")
    print(f"ChromaDB   : {'PASS' if ch_ok else 'WARN'} — {ch_msg}")
    print("---")

    critical_ok = pg_ok and rd_ok
    print(f"RESULT     : {'READY' if critical_ok else 'NOT READY'}")
    if not critical_ok:
        print(
            "Hint: start stack with "
            "`docker compose -f docker-compose.prod.yml up -d` "
            "from the repo root. If Postgres credentials were reset to "
            "postgres/mpai, recreate the volume: "
            "`docker compose -f docker-compose.prod.yml down -v` then up again."
        )
    return 0 if critical_ok else 1


if __name__ == "__main__":
    # Allow running when Docker publishes ports on localhost by rewriting hosts.
    if os.getenv("HEALTHCHECK_USE_LOCALHOST", "").lower() in {"1", "true", "yes"}:
        for key in ("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
            val = os.getenv(key, "")
            if val:
                os.environ[key] = (
                    val.replace("@postgres:", "@127.0.0.1:")
                    .replace("@redis:", "@127.0.0.1:")
                )
        os.environ["CHROMADB_HOST"] = "127.0.0.1"
        os.environ["CHROMA_SERVER_HOST"] = "127.0.0.1"
        os.environ["POSTGRES_SERVER"] = "127.0.0.1"
        os.environ["REDIS_HOST"] = "127.0.0.1"

    raise SystemExit(asyncio.run(main()))
