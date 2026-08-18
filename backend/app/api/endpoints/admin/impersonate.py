"""Admin impersonation endpoints (email / user_id / organization / end)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.admin import (
    PlatformRole,
    get_current_admin,
    get_current_superadmin_strict,
    is_impersonating,
    platform_role_of,
)
from app.api.endpoints.admin.common import (
    ACTION_END,
    IMPERSONATION_TTL_SECONDS,
    assert_admin_reauth,
    assert_impersonation_allowed,
    build_impersonation_response,
    decode_impersonation_token,
    require_platform_admin,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.rbac import get_current_user
from app.core.redis_client import (
    impersonation_token_fingerprint,
    revoke_impersonation_jti,
)
from app.core.security import TokenError, decode_access_token
from app.models.core_models import Company, UserCompanyWorkspace, UserRole
from app.models.users import User
from app.schemas.admin import (
    ImpersonateByEmailRequest,
    ImpersonationConfirmRequest,
    ImpersonationEndRequest,
    ImpersonationEndResponse,
    ImpersonationResponse,
)
from app.services.audit_service import audit_service

router = APIRouter(tags=["admin-impersonate"])


def _revoke_bearer_impersonation(raw: str) -> str | None:
    """Put the current impersonation token on the Redis denylist. Returns jti/fingerprint."""
    if raw.startswith("imp_"):
        token_id = impersonation_token_fingerprint(raw)
        revoke_impersonation_jti(token_id, ttl_seconds=IMPERSONATION_TTL_SECONDS)
        return token_id
    try:
        claims = decode_access_token(raw)
        if claims.get("typ") != "impersonation":
            return None
        jti = str(claims.get("jti") or "").strip() or None
        if not jti:
            jti = impersonation_token_fingerprint(raw)
        revoke_impersonation_jti(jti, ttl_seconds=IMPERSONATION_TTL_SECONDS)
        return jti
    except TokenError:
        # Still fingerprint opaque strings so end() can denylist stolen cookies.
        token_id = impersonation_token_fingerprint(raw)
        revoke_impersonation_jti(token_id, ttl_seconds=IMPERSONATION_TTL_SECONDS)
        return token_id


@router.post(
    "/impersonate",
    response_model=ImpersonationResponse,
    summary="Impersonate a client account by email",
)
@limiter.limit("10/minute")
async def impersonate_by_email(
    payload: ImpersonateByEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin_strict),
) -> ImpersonationResponse:
    if is_impersonating(current_user, request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Already impersonating. Exit the current session first.",
        )
    assert_admin_reauth(admin=current_user, password=payload.password)

    email = str(payload.user_email or payload.email).strip().lower()
    result = await db.execute(select(User).where(User.email.ilike(email)))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email '{email}' was not found.",
        )

    assert_impersonation_allowed(admin=current_user, target_user=target_user)
    response = await build_impersonation_response(
        db, admin=current_user, target_user=target_user, request=request
    )
    await db.commit()
    return response


@router.post(
    "/impersonate/user/{target_user_id}",
    response_model=ImpersonationResponse,
    summary="Impersonate a client account by user_id",
)
@limiter.limit("10/minute")
async def impersonate_by_user_id(
    target_user_id: uuid.UUID,
    payload: ImpersonationConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> ImpersonationResponse:
    require_platform_admin(current_user)
    if is_impersonating(current_user, request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Already impersonating. Exit the current session first.",
        )
    assert_admin_reauth(admin=current_user, password=payload.password)

    target_user = await db.get(User, target_user_id)
    if target_user is None or target_user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    assert_impersonation_allowed(admin=current_user, target_user=target_user)
    response = await build_impersonation_response(
        db, admin=current_user, target_user=target_user, request=request
    )
    await db.commit()
    return response


@router.post(
    "/impersonate/end",
    response_model=ImpersonationEndResponse,
    summary="End impersonation and revoke the current impersonation JWT",
)
async def end_impersonation_session(
    payload: ImpersonationEndRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImpersonationEndResponse:
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    admin_id = current_user.id
    target_id: uuid.UUID | None = payload.target_user_id
    revoked_jti: str | None = None

    if auth_header and auth_header.lower().startswith("bearer "):
        raw = auth_header.split(" ", 1)[1].strip()
        revoked_jti = _revoke_bearer_impersonation(raw)
        if raw.startswith("imp_"):
            decoded = decode_impersonation_token(raw)
            if decoded is not None:
                try:
                    admin_id = uuid.UUID(
                        str(decoded.get("impersonated_by") or decoded["actor_user_id"])
                    )
                    target_id = uuid.UUID(str(decoded["target_user_id"]))
                except (KeyError, ValueError):
                    pass
        else:
            try:
                claims = decode_access_token(raw)
                if claims.get("typ") == "impersonation":
                    admin_id = uuid.UUID(str(claims["impersonated_by"]))
                    target_id = uuid.UUID(str(claims["sub"]))
            except (TokenError, KeyError, ValueError):
                pass

    if target_id is None and payload.email:
        result = await db.execute(select(User).where(User.email.ilike(str(payload.email).strip())))
        target = result.scalar_one_or_none()
        if target is not None:
            target_id = target.id

    if target_id is None:
        target_id = current_user.id

    role = platform_role_of(current_user)
    is_staff = role in {PlatformRole.SUPERADMIN, PlatformRole.SUPPORT}
    session_impersonating = is_impersonating(current_user, request)
    if not is_staff and not session_impersonating:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges are required to end impersonation.",
        )

    await audit_service.write(
        db,
        admin_id=admin_id,
        target_user_id=target_id,
        action=ACTION_END,
        ip_address=audit_service.client_ip(request),
        details={"revoked_jti": revoked_jti} if revoked_jti else None,
    )
    await db.commit()
    logger.warning(
        "Admin.impersonate_end | actor={actor} target={target} jti={jti} ip={ip}",
        actor=admin_id,
        target=target_id,
        jti=revoked_jti,
        ip=audit_service.client_ip(request),
    )
    return ImpersonationEndResponse(
        message="Impersonation ended, token revoked, and audit logged.",
    )


@router.post(
    "/impersonate/{organization_id}",
    response_model=ImpersonationResponse,
    summary="Mint an ephemeral token to inspect a client organization workspace",
)
@limiter.limit("10/minute")
async def impersonate_organization(
    organization_id: uuid.UUID,
    payload: ImpersonationConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> ImpersonationResponse:
    require_platform_admin(current_user)
    if is_impersonating(current_user, request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Already impersonating. Exit the current session first.",
        )
    assert_admin_reauth(admin=current_user, password=payload.password)

    company = await db.get(Company, organization_id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{organization_id}' was not found.",
        )

    owner_result = await db.execute(
        select(User)
        .join(
            UserCompanyWorkspace,
            UserCompanyWorkspace.user_id == User.id,
        )
        .where(
            UserCompanyWorkspace.company_id == organization_id,
            UserCompanyWorkspace.role == UserRole.OWNER,
        )
        .order_by(User.created_at.asc())
        .limit(1)
    )
    target_user = owner_result.scalar_one_or_none()

    if target_user is None:
        member_result = await db.execute(
            select(User)
            .join(
                UserCompanyWorkspace,
                UserCompanyWorkspace.user_id == User.id,
            )
            .where(UserCompanyWorkspace.company_id == organization_id)
            .order_by(User.created_at.asc())
            .limit(1)
        )
        target_user = member_result.scalar_one_or_none()

    if target_user is None:
        target_user = await db.get(User, company.owner_user_id)

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No workspace member available for impersonation.",
        )

    assert_impersonation_allowed(admin=current_user, target_user=target_user)
    response = await build_impersonation_response(
        db, admin=current_user, target_user=target_user, request=request
    )
    await db.commit()
    return response
