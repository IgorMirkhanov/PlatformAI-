import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_v1_router
from app.core.config import settings
from app.core.database import DBSessionMiddleware
from app.core.fastapi_users_app import mount_fastapi_users
from app.core.logging_config import setup_logging
from app.core.middleware import (
    CorrelationIdMiddleware,
    ImpersonationMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import limiter
from app.core.telemetry import init_telemetry
from app.core.tenant import TenantMiddleware
from app.core.ws_pubsub import run_operator_ws_subscriber
from app.services.telegram_webhook_manager import register_all_webhooks


def _mark_request_error(request: Request) -> None:
    """Signal DBSessionMiddleware / get_db to roll back instead of commit."""
    request.state.error_occurred = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_telemetry()
    from app.core.crypto import validate_encryption_at_startup
    from app.core.otel import init_otel

    validate_encryption_at_startup()
    init_otel(app)
    logger.info(
        "Application.startup | env={env} tenant_base={tenant} cors={cors}",
        env=settings.ENVIRONMENT,
        tenant=settings.TENANT_BASE_DOMAIN,
        cors=settings.cors_allow_origins,
    )
    try:
        logger.info("[STARTUP] Запуск TelegramWebhookManager...")
        from app.core.config import webhook_base_is_public

        if not webhook_base_is_public():
            logger.warning(
                "[STARTUP] WEBHOOK_BASE_URL is not public HTTPS — Telegram will use "
                "Celery getUpdates polling. For commercial deploy set WEBHOOK_BASE_URL "
                "or NGROK_TUNNEL_URL to https://<public-host> and keep celery_worker up."
            )
        await register_all_webhooks()
        logger.info("TelegramWebhookManager.bootstrap_done")
    except Exception as e:
        logger.error(f" Ошибка TelegramWebhookManager: {e}")
    ws_subscriber_task = asyncio.create_task(run_operator_ws_subscriber())
    yield
    ws_subscriber_task.cancel()
    with suppress(asyncio.CancelledError):
        await ws_subscriber_task
    logger.info("Application.shutdown")


app = FastAPI(
    title="MP.AI",
    version="1.0.0",
    description=(
        "MP.AI multi-tenant AI bot SaaS.\n\n"
        "## Quick start\n"
        "1. `POST /api/v1/auth/login/json` with `{\"email\",\"password\"}` → `access_token`.\n"
        "2. `Authorization: Bearer <token>` on subsequent calls.\n"
        "3. Optional tenant: header `X-Tenant-ID: <organization uuid>`.\n"
        "4. Execute a bot turn: `POST /api/v1/bots/{bot_id}/execute` "
        "with `{\"message\":\"hello\"}`.\n\n"
        "User guides: `docs/user/getting-started.md`, "
        "`docs/user/creating-first-bot.md`.\n"
        "Architecture: `docs/architecture/SAAS_V1.md`."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "auth", "description": "JWT login, refresh, password reset, OAuth stubs"},
        {"name": "organizations", "description": "Tenant organizations for the current user"},
        {"name": "bots", "description": "Tenant-scoped bot listing (SaaS layout)"},
        {"name": "bot-management", "description": "Bots & flow save/publish"},
        {"name": "flow-execution", "description": "HTTP execute + streaming WS"},
        {"name": "flow-versions", "description": "Flow revision history / rollback"},
        {"name": "billing", "description": "Wallet & plans"},
        {"name": "billing-stripe", "description": "Stripe Checkout / webhooks"},
        {"name": "health-check", "description": "Liveness / readiness"},
        {"name": "sandbox", "description": "Internal flow preview (HTTP + WS)"},
    ],
)

app.state.limiter = limiter


def _correlation_id(request: Request) -> str | None:
    from app.core.middleware import get_correlation_id

    return get_correlation_id() or getattr(request.state, "correlation_id", None)


def _validation_fields(exc: RequestValidationError) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        parts = [
            str(part)
            for part in loc
            if part not in {"body", "query", "path", "header", "cookie"}
        ]
        field = ".".join(parts) if parts else (str(loc[-1]) if loc else "request")
        fields.append(
            {
                "field": field,
                "message": str(err.get("msg") or "Invalid value"),
            }
        )
    return fields


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    _mark_request_error(request)
    fields = _validation_fields(exc)
    logger.info(
        "Validation.error | path={path} fields={fields} correlation_id={cid}",
        path=request.url.path,
        fields=[f["field"] for f in fields],
        cid=_correlation_id(request),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Некорректные параметры запроса",
            "code": "VALIDATION_ERROR",
            "fields": fields,
            "correlation_id": _correlation_id(request),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code >= 400:
        _mark_request_error(request)
    headers = dict(exc.headers) if exc.headers else None
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    _mark_request_error(request)
    retry_after = getattr(exc, "retry_after", None) or 60
    try:
        retry_after_int = max(1, int(retry_after))
    except (TypeError, ValueError):
        retry_after_int = 60

    logger.warning(
        "RateLimit.exceeded | path={path} ip={ip} limit={limit} correlation_id={cid}",
        path=request.url.path,
        ip=request.client.host if request.client else None,
        limit=str(getattr(exc, "detail", "") or exc),
        cid=_correlation_id(request),
    )
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "Слишком много запросов. Подождите немного и попробуйте снова.",
            "code": "RATE_LIMIT_EXCEEDED",
            "retry_after": retry_after_int,
            "correlation_id": _correlation_id(request),
        },
        headers={"Retry-After": str(retry_after_int)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    from app.services.quota_service import QuotaExceeded

    _mark_request_error(request)

    if isinstance(exc, QuotaExceeded):
        return JSONResponse(
            status_code=402,
            content={
                "detail": {
                    "code": exc.code,
                    "message": exc.detail,
                    "billing_url": "/billing",
                },
                "correlation_id": _correlation_id(request),
            },
        )

    cid = _correlation_id(request)
    logger.exception(
        "Unhandled.error | path={path} correlation_id={cid} error={error}",
        path=request.url.path,
        cid=cid,
        error=str(exc),
    )

    # FastAPI exception handlers mark the error as "handled", so Sentry's
    # FastApiIntegration may skip it — capture explicitly with request context.
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("correlation_id", cid or "")
            scope.set_context(
                "request",
                {
                    "method": request.method,
                    "url": str(request.url),
                    "path": request.url.path,
                },
            )
            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001 — telemetry must never break the API response
        pass

    # Never leak stack traces / filesystem paths / exception types to clients.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal Server Error",
            "error_code": "INTERNAL_SERVER_ERROR",
            "correlation_id": cid,
        },
    )


# Order (last added = outermost):
# TrustedHost → CORS → SecurityHeaders → Impersonation → Correlation → Tenant → SlowAPI → DBSession
app.add_middleware(DBSessionMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(TenantMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(ImpersonationMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-Requested-With",
        "X-Tenant-ID",
        "X-Correlation-ID",
        "X-Impersonation-Token",
    ],
)
# Allow ngrok tunnel hosts (*.ngrok-free.dev / *.ngrok-free.app) alongside ALLOWED_HOSTS.
# When ALLOWED_HOSTS is unset, trusted_hosts is ["*"] so production domains stay open.
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.trusted_hosts,
)

app.include_router(api_v1_router)
mount_fastapi_users(app)

from app.core.metrics import metrics_router

app.include_router(metrics_router)

uploads_path = Path(settings.UPLOADS_DIR)
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")


@app.get("/healthcheck")
async def healthcheck() -> dict[str, Any]:
    """Lightweight health endpoint for container orchestrators."""
    from app.services.platform_health_service import platform_health_service

    postgres = await platform_health_service.check_postgresql()
    database_status = postgres.status
    overall = "ok" if database_status == "up" else "degraded"

    return {
        "status": overall,
        "service": "mp.ai-platform",
        "database": {
            "status": database_status,
            "latency_ms": postgres.latency_ms,
            "detail": postgres.detail,
        },
        "probes": {
            "live": "/api/v1/health/live",
            "ready": "/api/v1/health/ready",
            "metrics": "/api/v1/health/metrics",
        },
        "auth": "/api/v1/auth/login",
    }
