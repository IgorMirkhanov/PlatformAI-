"""Prometheus metrics for MP.AI (optional if prometheus_client missing)."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.tenant import has_internal_service_key

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    LLM_REQUESTS = Counter("mpai_llm_requests_total", "LLM completions", ["status"])
    LLM_TOKENS = Counter("mpai_llm_tokens_total", "LLM tokens consumed", ["direction"])
    USAGE_EVENTS = Counter("mpai_usage_events_total", "Usage meter events", ["metric"])
    WEBHOOK_LATENCY = Histogram(
        "mpai_webhook_seconds",
        "Webhook handling latency",
        ["platform"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    )
    HTTP_REQUESTS = Counter("mpai_http_requests_total", "HTTP requests", ["method", "code"])
    GUARDRAIL_BLOCKS = Counter("mpai_guardrail_blocks_total", "Blocked by AI guardrails", ["reason"])
    WEBHOOK_FAILURES = Counter(
        "mpai_webhook_failures_total",
        "Webhook handler failures",
        ["platform"],
    )
    WEBHOOK_EVENTS = Counter("webhook_events_total", "Inbound webhook outcomes", ["provider", "status"])
    AI_PROVIDER_LATENCY = Histogram(
        "ai_provider_latency_seconds",
        "LLM provider latency",
        ["provider", "model"],
        buckets=(0.25, 0.5, 1, 2, 4, 8, 12, 20, 45),
    )
    CRM_LEAD_CREATE = Counter("crm_lead_create_total", "CRM lead create attempts", ["crm", "result"])
    OAUTH_REFRESH = Counter("oauth_refresh_total", "OAuth token refresh attempts", ["crm", "result"])
    WALLET_BLOCKED = Counter(
        "wallet_blocked_events_total",
        "Organization token wallet blocked / insufficient events",
        ["reason"],
    )

    def metrics_payload() -> tuple[bytes, str]:
        return generate_latest(), CONTENT_TYPE_LATEST

except ImportError:  # pragma: no cover

    class _Noop:
        def labels(self, *_, **__):
            return self

        def inc(self, *_a, **_k):
            return None

        def observe(self, *_a, **_k):
            return None

    LLM_REQUESTS = _Noop()
    LLM_TOKENS = _Noop()
    USAGE_EVENTS = _Noop()
    WEBHOOK_LATENCY = _Noop()
    HTTP_REQUESTS = _Noop()
    GUARDRAIL_BLOCKS = _Noop()
    WEBHOOK_FAILURES = _Noop()
    WEBHOOK_EVENTS = _Noop()
    AI_PROVIDER_LATENCY = _Noop()
    CRM_LEAD_CREATE = _Noop()
    OAUTH_REFRESH = _Noop()
    WALLET_BLOCKED = _Noop()

    def metrics_payload() -> tuple[bytes, str]:
        body = b"# prometheus_client not installed\n"
        return body, "text/plain; charset=utf-8"


def record_http_request(method: str, status_code: int) -> None:
    HTTP_REQUESTS.labels(method=(method or "GET").upper(), code=str(status_code)).inc()


def record_webhook_failure(platform: str) -> None:
    WEBHOOK_FAILURES.labels(platform=(platform or "unknown").lower()).inc()


def record_webhook_event(provider: str, status_label: str) -> None:
    WEBHOOK_EVENTS.labels(
        provider=(provider or "unknown").lower(),
        status=(status_label or "unknown").lower(),
    ).inc()


def observe_ai_latency(provider: str, model: str, seconds: float) -> None:
    AI_PROVIDER_LATENCY.labels(
        provider=(provider or "unknown").lower(),
        model=(model or "unknown")[:64],
    ).observe(max(0.0, float(seconds)))


def record_crm_lead(crm: str, result: str) -> None:
    CRM_LEAD_CREATE.labels(crm=(crm or "unknown").lower(), result=(result or "error").lower()).inc()


def record_oauth_refresh(crm: str, result: str) -> None:
    OAUTH_REFRESH.labels(crm=(crm or "unknown").lower(), result=(result or "error").lower()).inc()


def record_wallet_blocked(reason: str) -> None:
    WALLET_BLOCKED.labels(reason=(reason or "unknown")[:64]).inc()


metrics_router = APIRouter(tags=["metrics"])


def _assert_metrics_access(request: Request) -> None:
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
        detail="Metrics scrape requires authentication.",
    )


@metrics_router.get("/metrics")
async def prometheus_metrics(request: Request) -> Response:
    _assert_metrics_access(request)
    body, content_type = metrics_payload()
    return Response(content=body, media_type=content_type)

