from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx
import redis
from loguru import logger
from sqlalchemy import text

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import engine
from app.schemas.health_schemas import (
    CeleryClusterHealth,
    DependencyHealth,
    PlatformHealthResponse,
)


class PlatformHealthService:
    """Deep readiness probes for load balancers and observability stacks."""

    async def check_postgresql(self) -> DependencyHealth:
        started = time.perf_counter()
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return DependencyHealth(status="up", latency_ms=latency_ms)
        except Exception as exc:
            logger.warning("Health.postgres_failed | error={error}", error=str(exc))
            return DependencyHealth(status="down", detail=str(exc))

    def check_redis(self) -> DependencyHealth:
        started = time.perf_counter()
        try:
            client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            info = client.info(section="memory")
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return DependencyHealth(
                status="up",
                latency_ms=latency_ms,
                metadata={
                    "used_memory_human": info.get("used_memory_human"),
                    "connected_clients": client.info("clients").get("connected_clients"),
                },
            )
        except Exception as exc:
            logger.warning("Health.redis_failed | error={error}", error=str(exc))
            return DependencyHealth(status="down", detail=str(exc))

    async def check_chromadb(self) -> DependencyHealth:
        host = getattr(settings, "CHROMA_SERVER_HOST", None)
        if not host:
            return DependencyHealth(
                status="up",
                detail="embedded_persistent_client",
                metadata={"mode": "local"},
            )

        port = int(getattr(settings, "CHROMA_SERVER_PORT", 8000))
        url = f"http://{host}:{port}/api/v1/heartbeat"
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url)
                response.raise_for_status()
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return DependencyHealth(
                status="up",
                latency_ms=latency_ms,
                metadata={"host": host, "port": port},
            )
        except Exception as exc:
            logger.warning("Health.chromadb_failed | error={error}", error=str(exc))
            return DependencyHealth(status="down", detail=str(exc))

    def check_celery_clusters(self) -> CeleryClusterHealth:
        try:
            inspector = celery_app.control.inspect(timeout=3.0)
            ping = inspector.ping() or {}
            active_queues = inspector.active_queues() or {}

            inbound_workers: list[str] = []
            crm_workers: list[str] = []
            for worker_name, queues in active_queues.items():
                queue_names = {entry.get("name") for entry in queues if entry.get("name")}
                if settings.CELERY_INBOUND_QUEUE in queue_names:
                    inbound_workers.append(worker_name)
                if settings.CELERY_CRM_QUEUE in queue_names:
                    crm_workers.append(worker_name)

            workers_online = len(ping)
            if workers_online == 0:
                return CeleryClusterHealth(
                    status="down",
                    workers_online=0,
                    detail="No Celery workers responded to ping.",
                )

            missing_inbound = not inbound_workers
            missing_crm = not crm_workers
            if missing_inbound or missing_crm:
                return CeleryClusterHealth(
                    status="degraded",
                    workers_online=workers_online,
                    inbound_workers=inbound_workers,
                    crm_workers=crm_workers,
                    detail="One or more dedicated worker queues are offline.",
                )

            return CeleryClusterHealth(
                status="up",
                workers_online=workers_online,
                inbound_workers=inbound_workers,
                crm_workers=crm_workers,
            )
        except Exception as exc:
            logger.warning("Health.celery_failed | error={error}", error=str(exc))
            return CeleryClusterHealth(status="down", detail=str(exc))

    async def collect_readiness(self) -> PlatformHealthResponse:
        postgres = await self.check_postgresql()
        redis_health = self.check_redis()
        chroma = await self.check_chromadb()
        celery = self.check_celery_clusters()

        checks = {
            "postgresql": postgres,
            "redis": redis_health,
            "chromadb": chroma,
        }

        critical_up = all(check.status == "up" for check in checks.values())
        celery_ok = celery.status in {"up", "degraded"}
        ready = critical_up and celery.status == "up"

        if not critical_up or celery.status == "down":
            overall = "unhealthy"
        elif celery.status == "degraded":
            overall = "degraded"
        else:
            overall = "healthy"

        return PlatformHealthResponse(
            status=overall,
            checks=checks,
            celery=celery,
            ready=ready,
            timestamp=datetime.now(UTC).isoformat(),
        )


platform_health_service = PlatformHealthService()
