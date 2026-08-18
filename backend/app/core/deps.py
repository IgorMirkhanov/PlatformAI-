"""Shared FastAPI dependencies for SaaS core (tenant + repos)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_user_from_bearer, oauth2_scheme
from app.core.database import get_db
from app.core.tenant import TenantContext, get_tenant, set_tenant
from app.models.users import User
from app.repositories.bot_repository import BotRepository, bot_repository
from app.repositories.organization_repository import (
    OrganizationRepository,
    organization_repository,
)


async def resolve_tenant_organization_id(
    request: Request,
    db: AsyncSession,
    current_user: User | None = None,
) -> uuid.UUID | None:
    """
    Resolve active organization id.

    Security rules:
      * Regular users are bound to the verified ``current_user.company_id``
        (JWT claim / membership-checked workspace switch in RBAC).
      * Spoofed ``X-Tenant-Id`` values set by middleware are ignored unless the
        middleware marked ``header_override_allowed`` (internal key / superadmin).
      * Slug → UUID resolution still runs for subdomain / internal slug headers.
    """
    ctx = getattr(request.state, "tenant", None) or get_tenant() or TenantContext()
    is_superadmin = bool(getattr(current_user, "is_superadmin", False)) if current_user else False

    # Hard bind authenticated tenants to the verified workspace on the user object.
    if current_user is not None and not is_superadmin:
        company_id = getattr(current_user, "company_id", None)
        if company_id is not None:
            # Reject middleware header spoof even if somehow present.
            if ctx.source in {"header", "invalid_header"} or (
                ctx.organization_id is not None
                and ctx.organization_id != company_id
                and not getattr(ctx, "header_override_allowed", False)
            ):
                logger.warning(
                    "Deps.tenant_spoof_blocked | user={user} spoof={spoof} bound={bound}",
                    user=current_user.id,
                    spoof=ctx.organization_id,
                    bound=company_id,
                )
            ctx.organization_id = company_id
            ctx.source = "jwt"
            request.state.tenant = ctx
            set_tenant(ctx)
            return company_id

    # Superadmin / internal / anonymous: honor trusted middleware context.
    if ctx.organization_id is not None:
        if ctx.source in {"header", "invalid_header"} and not getattr(
            ctx, "header_override_allowed", False
        ):
            # Legacy/untrusted header path — drop it.
            ctx.organization_id = None
            ctx.source = "none"
        else:
            return ctx.organization_id

    if ctx.organization_slug:
        from app.repositories.organization_repository import OrganizationRepository

        # Slug from client header is only trusted when override was allowed.
        if ctx.source in {"subdomain", "internal", "superadmin_header"} or getattr(
            ctx, "header_override_allowed", False
        ):
            org = await OrganizationRepository(db).get_by_slug(ctx.organization_slug)
            if org is not None:
                ctx.organization_id = org.id
                request.state.tenant = ctx
                set_tenant(ctx)
                return org.id

    if current_user is not None and getattr(current_user, "company_id", None):
        ctx.organization_id = current_user.company_id
        if ctx.source == "none":
            ctx.source = "jwt"
        request.state.tenant = ctx
        set_tenant(ctx)
        return current_user.company_id

    return None


async def get_optional_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str | None, Depends(oauth2_scheme)],
    x_company_id: Annotated[str | None, Header(alias="X-Company-Id")] = None,
) -> User | None:
    return await get_user_from_bearer(db, token, x_company_id=x_company_id)


async def get_tenant_id(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User | None, Depends(get_optional_user)],
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> uuid.UUID | None:
    """
    Dependency: resolved tenant id.

    ``X-Tenant-ID`` is documented for OpenAPI / internal callers only. Spoofed
    client headers are ignored unless ``TenantMiddleware`` allowed an override.
    """
    _ = x_tenant_id
    return await resolve_tenant_organization_id(request, db, user)


async def require_tenant_id(
    tenant_id: Annotated[uuid.UUID | None, Depends(get_tenant_id)],
) -> uuid.UUID:
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant required. Authenticate with an org-scoped JWT (or internal API key).",
        )
    return tenant_id


def get_bot_repo(
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[uuid.UUID | None, Depends(get_tenant_id)],
) -> BotRepository:
    return bot_repository(db, tenant_id)


def get_org_repo(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationRepository:
    return organization_repository(db)


TenantId = Annotated[uuid.UUID, Depends(require_tenant_id)]
OptionalTenantId = Annotated[uuid.UUID | None, Depends(get_tenant_id)]
BotRepo = Annotated[BotRepository, Depends(get_bot_repo)]
OrgRepo = Annotated[OrganizationRepository, Depends(get_org_repo)]

__all__ = [
    "CurrentUser",
    "TenantId",
    "OptionalTenantId",
    "BotRepo",
    "OrgRepo",
    "resolve_tenant_organization_id",
    "get_tenant_id",
    "require_tenant_id",
]
