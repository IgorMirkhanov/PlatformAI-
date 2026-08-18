"""Correlation ID + request context middleware."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)

CORRELATION_HEADER = "X-Correlation-ID"


def get_correlation_id() -> str | None:
    return correlation_id_ctx.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Attach a correlation ID to every request/response and bind it into loguru
    so structured logs can be traced end-to-end.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(CORRELATION_HEADER) or request.headers.get(
            "X-Request-ID"
        )
        cid = (incoming or "").strip() or str(uuid.uuid4())
        request.state.correlation_id = cid
        token = correlation_id_ctx.set(cid)
        with logger.contextualize(correlation_id=cid):
            try:
                response = await call_next(request)
            finally:
                correlation_id_ctx.reset(token)
        response.headers[CORRELATION_HEADER] = cid
        return response
