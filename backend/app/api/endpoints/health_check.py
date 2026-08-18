import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission, get_current_user
from app.core.tenant import has_internal_service_key
from app.core.config import settings
from app.models.core_models import Bot
from app.models.users import User
from app.schemas.core_schemas import BotHealthListResponse, BotHealthTelemetry
from app.schemas.health_schemas import LivenessResponse, PlatformHealthResponse
from app.services.bot_management_service import bot_management_service
from app.services.platform_health_service import platform_health_service

router = APIRouter(prefix="/health", tags=["health-check"])


def _assert_deep_health_access(request: Request) -> None:
    """Protect deep health/metrics: internal key or JWT staff in production."""
    if has_internal_service_key(request):
        return
    scrape = (getattr(settings, "METRICS_SCRAPE_TOKEN", None) or "").strip()
    provided = (request.headers.get("x-metrics-token") or "").strip()
    if scrape and provided and secrets.compare_digest(provided, scrape):
        return
    if not settings.is_production:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Deep health probes require internal authentication.",
    )


@router.get("/live", response_model=LivenessResponse)
async def liveness_probe() -> LivenessResponse:
    """Process liveness probe for orchestrators and edge load balancers."""
    return LivenessResponse()


@router.get("/ready", response_model=PlatformHealthResponse)
async def readiness_probe(request: Request, response: Response) -> PlatformHealthResponse:
    """Deep readiness probe with PostgreSQL, Redis, ChromaDB, and Celery cluster checks."""
    _assert_deep_health_access(request)
    try:
        payload = await platform_health_service.collect_readiness()
    except Exception as exc:
        logger.exception("HealthCheck.readiness_failed | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Readiness probe failed.",
        ) from exc

    if not payload.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif payload.status == "degraded":
        response.status_code = status.HTTP_200_OK
    return payload


@router.get("/metrics", response_model=PlatformHealthResponse)
async def platform_metrics(request: Request) -> PlatformHealthResponse:
    """Detailed internal telemetry snapshot for monitoring dashboards and alert hooks."""
    _assert_deep_health_access(request)
    return await platform_health_service.collect_readiness()


@router.get("/bots", response_model=BotHealthListResponse)
async def list_bots_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BotHealthListResponse:
    """Tenant-scoped bot telemetry (superadmin/support can see all)."""
    try:
        include_all = bool(
            getattr(current_user, "is_superadmin", False)
            or getattr(current_user, "is_support", False)
        )
        return await bot_management_service.list_bots_health(
            db,
            organization_id=None if include_all else current_user.company_id,
            include_all=include_all,
        )
    except Exception as exc:
        logger.exception("HealthCheck.list_failed | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load bot health telemetry.",
        ) from exc


@router.get("/bots/{bot_id}", response_model=BotHealthTelemetry)
async def get_bot_health(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.DASHBOARD_READ)),
) -> BotHealthTelemetry:
    """Verify a single bot has a valid published graph and active channel integration."""
    try:
        return await bot_management_service.get_bot_health(db, bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "HealthCheck.bot_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load bot health telemetry.",
        ) from exc
