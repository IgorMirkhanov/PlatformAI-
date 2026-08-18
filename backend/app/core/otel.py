"""OpenTelemetry bootstrap — no-op when OTEL endpoint unset."""

from __future__ import annotations

from loguru import logger

from app.core.config import settings


def init_otel(app=None) -> None:
    endpoint = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip()
    if not endpoint:
        logger.debug("OTel.disabled | reason=no_endpoint")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OTel.skipped | reason=packages_not_installed")
        return

    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "deployment.environment": settings.ENVIRONMENT,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    if app is not None:
        FastAPIInstrumentor.instrument_app(app)
    logger.info("OTel.enabled | endpoint={endpoint}", endpoint=endpoint)
