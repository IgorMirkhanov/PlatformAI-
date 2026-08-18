"""Tenant (Organization) request context — JWT-bound, header spoofing hardened."""

from __future__ import annotations

import re
import secrets
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")

tenant_ctx: ContextVar["TenantContext | None"] = ContextVar("tenant_ctx", default=None)

# Headers that must never be trusted from anonymous / regular tenant clients.
_ORG_ID_HEADERS = ("x-tenant-id", "x-company-id", "x-organization-id")
_ORG_SLUG_HEADERS = ("x-tenant-slug", "x-organization-slug")
_INTERNAL_KEY_HEADERS = ("x-internal-api-key", "x-service-api-key")


@dataclass(slots=True)
class TenantContext:
    """Resolved tenant for the current request."""

    organization_id: uuid.UUID | None = None
    organization_slug: str | None = None
    project_id: uuid.UUID | None = None
    source: str = "none"  # jwt | internal | superadmin_header | subdomain | none
    header_override_allowed: bool = False


def get_tenant() -> TenantContext | None:
    return tenant_ctx.get()


def set_tenant(ctx: TenantContext | None) -> None:
    tenant_ctx.set(ctx)


def extract_subdomain(host: str | None, base_domain: str | None) -> str | None:
    """
    Extract tenant slug from Host header.

    Example: acme.app.example.com + base=app.example.com → acme
    """
    if not host or not base_domain:
        return None
    hostname = host.split(":", 1)[0].strip().lower()
    base = base_domain.strip().lower().lstrip(".")
    if hostname in {base, f"www.{base}", "localhost", "127.0.0.1"}:
        return None
    suffix = f".{base}"
    if not hostname.endswith(suffix):
        return None
    slug = hostname[: -len(suffix)]
    if not slug or "." in slug or not _SLUG_RE.match(slug):
        return None
    if slug in {"www", "api", "app", "admin"}:
        return None
    return slug


def _bearer_claims(request: Request) -> dict:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return {}
    raw = auth.split(" ", 1)[1].strip()
    if not raw or raw.startswith("imp_"):
        return {}
    try:
        from app.core.security import decode_access_token

        claims = decode_access_token(raw)
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def has_internal_service_key(request: Request) -> bool:
    """True when the caller presents the shared internal microservice API key."""
    expected = (getattr(settings, "INTERNAL_SERVICE_API_KEY", None) or "").strip()
    if not expected:
        return False
    for header in _INTERNAL_KEY_HEADERS:
        provided = (request.headers.get(header) or "").strip()
        if provided and secrets.compare_digest(provided, expected):
            return True
    return False


def caller_is_superadmin_from_jwt(claims: dict) -> bool:
    return bool(claims.get("is_superuser") or claims.get("is_superadmin"))


def allow_tenant_header_override(request: Request, claims: dict | None = None) -> bool:
    """
    Org-id headers are trusted only for:
      * internal microservices (``X-Internal-Api-Key``), or
      * platform superadmins (JWT ``is_superuser`` claim).
    """
    if has_internal_service_key(request):
        return True
    claims = claims if claims is not None else _bearer_claims(request)
    return caller_is_superadmin_from_jwt(claims)


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Resolve Organization tenant from (priority):

      1. Signed JWT ``company_id`` (default for all authenticated tenants)
      2. ``X-Tenant-Id`` / ``X-Organization-Id`` — **only** with internal API key
         or superadmin JWT (never trusted from regular clients)
      3. Subdomain of ``TENANT_BASE_DOMAIN`` (host-based, not client org spoof)
      4. Optional ``X-Project-Id``

    Membership enforcement for workspace switching remains in RBAC / ``deps``.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        ctx = TenantContext()
        claims = _bearer_claims(request)
        header_ok = allow_tenant_header_override(request, claims)
        ctx.header_override_allowed = header_ok

        org_header = None
        for name in _ORG_ID_HEADERS:
            value = request.headers.get(name)
            if value and value.strip():
                org_header = value.strip()
                break

        slug_header = None
        for name in _ORG_SLUG_HEADERS:
            value = request.headers.get(name)
            if value and value.strip():
                slug_header = value.strip().lower()
                break

        project_header = request.headers.get("x-project-id")

        # 1) JWT company_id is the authoritative tenant for normal users.
        company_claim = claims.get("company_id") or claims.get("organization_id")
        if company_claim:
            try:
                ctx.organization_id = uuid.UUID(str(company_claim))
                ctx.source = "jwt"
            except ValueError:
                logger.warning("Tenant.invalid_jwt_company_id | claim={claim}", claim=company_claim)

        # 2) Header override — internal services / superadmins only.
        if org_header:
            if header_ok:
                try:
                    ctx.organization_id = uuid.UUID(org_header)
                    ctx.source = "internal" if has_internal_service_key(request) else "superadmin_header"
                except ValueError:
                    logger.warning("Tenant.invalid_org_header | value={value}", value=org_header[:64])
            else:
                logger.warning(
                    "Tenant.org_header_ignored | spoof_blocked path={path}",
                    path=request.url.path,
                )

        if slug_header and _SLUG_RE.match(slug_header):
            if header_ok:
                ctx.organization_slug = slug_header
                if ctx.source in {"none", "jwt"} and has_internal_service_key(request):
                    ctx.source = "internal"
            elif ctx.organization_id is None:
                # Do not let clients pick another tenant by slug header.
                logger.warning(
                    "Tenant.slug_header_ignored | spoof_blocked path={path}",
                    path=request.url.path,
                )

        # 3) Subdomain fallback when still unresolved.
        if ctx.organization_id is None and ctx.organization_slug is None:
            sub = extract_subdomain(
                request.headers.get("host"),
                getattr(settings, "TENANT_BASE_DOMAIN", None),
            )
            if sub:
                ctx.organization_slug = sub
                ctx.source = "subdomain"

        if project_header:
            try:
                ctx.project_id = uuid.UUID(project_header.strip())
            except ValueError:
                pass

        request.state.tenant = ctx
        token = tenant_ctx.set(ctx)
        try:
            response = await call_next(request)
            if ctx.organization_id:
                response.headers["X-Resolved-Tenant-Id"] = str(ctx.organization_id)
            elif ctx.organization_slug:
                response.headers["X-Resolved-Tenant-Slug"] = ctx.organization_slug
            return response
        finally:
            tenant_ctx.reset(token)
