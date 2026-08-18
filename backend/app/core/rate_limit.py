"""SlowAPI rate limiting — shared Limiter + keyed helpers for auth / billing / org."""

from __future__ import annotations

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.security import TokenError


def _bearer_claims(request: Request) -> dict:
    """Verified JWT claims for rate-limit keys (signature + expiry checked)."""
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return {}
    token = auth.split(" ", 1)[1].strip()
    if not token or token.startswith("imp_"):
        return {}
    try:
        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        return payload if isinstance(payload, dict) else {}
    except TokenError:
        return {}


def rate_limit_key_ip(request: Request) -> str:
    return f"ip:{get_remote_address(request)}"


def rate_limit_key_user(request: Request) -> str:
    """Prefer authenticated user id; fall back to IP."""
    claims = _bearer_claims(request)
    sub = claims.get("sub")
    if sub:
        return f"user:{sub}"
    return rate_limit_key_ip(request)


def rate_limit_key_org(request: Request) -> str:
    """
    Prefer tenant context from request state or verified JWT.

    Never trust ``?organization_id=`` / any query string — unauthenticated
    callers could exhaust another tenant's quota. Fall back to user id, then IP.
    """
    # Intentionally ignore request.query_params (DoS via org spoofing).
    state_org = getattr(request.state, "crm_organization_id", None) or getattr(
        request.state, "organization_id", None
    )
    if state_org:
        return f"org:{state_org}"
    claims = _bearer_claims(request)
    org_id = claims.get("company_id") or claims.get("organization_id")
    if org_id:
        return f"org:{org_id}"
    sub = claims.get("sub")
    if sub:
        return f"user:{sub}"
    return rate_limit_key_ip(request)


def _extract_crm_api_key_header(request: Request) -> str | None:
    header_key = request.headers.get("X-CRM-API-Key")
    if header_key and header_key.strip():
        return header_key.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            return token
    return None


def rate_limit_key_crm_public(request: Request) -> str:
    """
    Public CRM ingress: bucket by API-key fingerprint (or IP when missing).

    Org id from query string is intentionally ignored.
    """
    raw = _extract_crm_api_key_header(request)
    if raw:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        return f"crm_key:{digest}"
    state_org = getattr(request.state, "crm_organization_id", None)
    if state_org:
        return f"org:{state_org}"
    return rate_limit_key_ip(request)


limiter = Limiter(
    key_func=rate_limit_key_ip,
    default_limits=[settings.RATE_LIMIT_DEFAULT] if settings.RATE_LIMIT_ENABLED else [],
    enabled=settings.RATE_LIMIT_ENABLED,
)
