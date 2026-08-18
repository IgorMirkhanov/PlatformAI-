"""Admin system health probes — Postgres, Redis, Celery, Chroma, WhatsApp."""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superadmin
from app.core.config import settings
from app.core.database import get_db
from app.models.users import User

router = APIRouter(tags=["admin-health"])

ComponentStatus = Literal["ok", "degraded", "error"]
PlatformState = Literal["healthy", "degraded", "down"]


class HealthComponent(BaseModel):
    name: str
    status: ComponentStatus
    latency_ms: float | None = None
    detail: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SystemHealthResponse(BaseModel):
    status: PlatformState
    checked_at: str
    components: list[HealthComponent]


def _aggregate(components: list[HealthComponent]) -> PlatformState:
    statuses = {c.status for c in components}
    if "error" in statuses and all(c.status == "error" for c in components):
        return "down"
    if "error" in statuses or "degraded" in statuses:
        # Critical path: DB error alone → down
        db = next((c for c in components if c.name == "postgresql"), None)
        if db is not None and db.status == "error":
            return "down"
        return "degraded"
    return "healthy"


async def _check_postgres(db: AsyncSession) -> HealthComponent:
    started = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        latency = round((time.perf_counter() - started) * 1000, 2)
        return HealthComponent(
            name="postgresql",
            status="ok",
            latency_ms=latency,
            detail="SELECT 1 ok",
        )
    except Exception as exc:
        latency = round((time.perf_counter() - started) * 1000, 2)
        logger.warning("AdminHealth.postgres_error | error={error}", error=str(exc))
        return HealthComponent(
            name="postgresql",
            status="error",
            latency_ms=latency,
            detail=str(exc)[:240],
        )


def _check_redis() -> HealthComponent:
    started = time.perf_counter()
    try:
        from app.core.redis_client import get_redis_client

        client = get_redis_client()
        pong = client.ping()
        info = {}
        try:
            raw = client.info("memory")
            used = raw.get("used_memory_human") or raw.get("used_memory")
            info = {
                "used_memory_human": used,
                "used_memory": raw.get("used_memory"),
                "maxmemory_human": raw.get("maxmemory_human"),
            }
        except Exception:
            pass
        latency = round((time.perf_counter() - started) * 1000, 2)
        return HealthComponent(
            name="redis",
            status="ok" if pong else "degraded",
            latency_ms=latency,
            detail="PONG" if pong else "ping failed",
            meta=info,
        )
    except Exception as exc:
        latency = round((time.perf_counter() - started) * 1000, 2)
        return HealthComponent(
            name="redis",
            status="error",
            latency_ms=latency,
            detail=str(exc)[:240],
        )


def _check_celery() -> HealthComponent:
    started = time.perf_counter()
    try:
        from app.core.celery_app import celery_app

        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            latency = round((time.perf_counter() - started) * 1000, 2)
            return HealthComponent(
                name="celery",
                status="degraded",
                latency_ms=latency,
                detail="CELERY_TASK_ALWAYS_EAGER — workers not required",
                meta={"active_workers": 0, "eager": True},
            )

        inspector = celery_app.control.inspect(timeout=1.0)
        ping = inspector.ping() if inspector else None
        active_workers = len(ping or {})
        latency = round((time.perf_counter() - started) * 1000, 2)
        if active_workers <= 0:
            return HealthComponent(
                name="celery",
                status="error",
                latency_ms=latency,
                detail="No active Celery workers",
                meta={"active_workers": 0},
            )
        return HealthComponent(
            name="celery",
            status="ok",
            latency_ms=latency,
            detail=f"{active_workers} worker(s) online",
            meta={"active_workers": active_workers, "workers": list((ping or {}).keys())},
        )
    except Exception as exc:
        latency = round((time.perf_counter() - started) * 1000, 2)
        return HealthComponent(
            name="celery",
            status="error",
            latency_ms=latency,
            detail=str(exc)[:240],
            meta={"active_workers": 0},
        )


def _check_chroma() -> HealthComponent:
    started = time.perf_counter()
    try:
        from app.core.vector_db import _get_chroma_client

        client = _get_chroma_client()
        # Lightweight heartbeat — list collections or heartbeat API.
        heartbeat = None
        if hasattr(client, "heartbeat"):
            heartbeat = client.heartbeat()
        else:
            _ = client.list_collections()
        latency = round((time.perf_counter() - started) * 1000, 2)
        return HealthComponent(
            name="chromadb",
            status="ok",
            latency_ms=latency,
            detail="reachable",
            meta={"heartbeat": heartbeat},
        )
    except Exception as exc:
        latency = round((time.perf_counter() - started) * 1000, 2)
        return HealthComponent(
            name="chromadb",
            status="error",
            latency_ms=latency,
            detail=str(exc)[:240],
        )


async def _check_whatsapp() -> HealthComponent:
    started = time.perf_counter()
    base = (settings.WHATSAPP_SERVICE_URL or "").rstrip("/")
    if not base:
        return HealthComponent(
            name="whatsapp",
            status="degraded",
            detail="WHATSAPP_SERVICE_URL not configured",
        )
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(f"{base}/health")
            latency = round((time.perf_counter() - started) * 1000, 2)
            payload: dict[str, Any] = {}
            try:
                payload = response.json()
            except Exception:
                payload = {"raw": response.text[:200]}
            sessions = payload.get("sessions") if isinstance(payload, dict) else None
            active = 0
            if isinstance(sessions, list):
                active = sum(
                    1
                    for s in sessions
                    if isinstance(s, dict) and str(s.get("status") or "").lower() in {
                        "connected",
                        "open",
                        "ready",
                    }
                )
            status: ComponentStatus = "ok" if response.is_success else "error"
            if response.is_success and active == 0 and isinstance(sessions, list) and len(sessions) == 0:
                status = "degraded"
            return HealthComponent(
                name="whatsapp",
                status=status,
                latency_ms=latency,
                detail=f"HTTP {response.status_code}",
                meta={
                    "session_count": len(sessions) if isinstance(sessions, list) else None,
                    "active_sessions": active,
                },
            )
    except Exception as exc:
        latency = round((time.perf_counter() - started) * 1000, 2)
        return HealthComponent(
            name="whatsapp",
            status="error",
            latency_ms=latency,
            detail=str(exc)[:240],
        )


@router.get(
    "/system-health",
    response_model=SystemHealthResponse,
    summary="Platform dependency health (DB, Redis, Celery, Chroma, WhatsApp)",
)
async def get_system_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> SystemHealthResponse:
    _ = current_user
    from datetime import UTC, datetime

    components = [
        await _check_postgres(db),
        _check_redis(),
        _check_celery(),
        _check_chroma(),
        await _check_whatsapp(),
    ]
    state = _aggregate(components)
    return SystemHealthResponse(
        status=state,
        checked_at=datetime.now(UTC).isoformat(),
        components=components,
    )
