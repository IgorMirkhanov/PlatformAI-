"""Impersonation request-state middleware."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class ImpersonationMiddleware(BaseHTTPMiddleware):
    """
    Lightweight parser that stamps ``request.state`` when an impersonation
    Bearer is present (``imp_*`` HMAC tokens or JWT ``typ=impersonation``).

    Full identity resolution still happens in ``get_current_user``; this
    middleware only exposes flags for route guards / logging.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.is_impersonating = False
        request.state.impersonated_by = None
        request.state.real_user_id = None

        auth = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            raw = auth.split(" ", 1)[1].strip()
            if raw.startswith("imp_"):
                try:
                    from app.api.endpoints.admin.common import decode_impersonation_token

                    payload = decode_impersonation_token(raw)
                    if payload:
                        request.state.is_impersonating = True
                        request.state.impersonated_by = uuid.UUID(
                            str(payload.get("impersonated_by") or payload.get("actor_user_id"))
                        )
                        request.state.real_user_id = request.state.impersonated_by
                except Exception:
                    pass
            else:
                try:
                    from app.core.security import decode_access_token

                    claims = decode_access_token(raw)
                    if claims.get("typ") == "impersonation":
                        request.state.is_impersonating = True
                        request.state.impersonated_by = uuid.UUID(str(claims["impersonated_by"]))
                        request.state.real_user_id = request.state.impersonated_by
                except Exception:
                    pass

        return await call_next(request)
