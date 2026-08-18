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

    def metrics_payload() -> tuple[bytes, str]:
        body = b"# prometheus_client not installed\n"
        return body, "text/plain; charset=utf-8"


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

