"""SaaS auth routers — refresh, password reset, OAuth stubs.

Primary login/register remain at ``app.api.endpoints.auth`` (tokenUrl stable).
This module adds extended auth under the same ``/auth`` prefix via aggregate router.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import mint_user_token, slugify_org_name
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    OAuthStubCallbackRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenPairResponse,
)
from app.services.auth_token_service import auth_token_service, email_stub
from app.services.team_service import team_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return ua, ip


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Rotate refresh token → new access + refresh pair",
)
@limiter.limit("30/minute")
async def refresh_tokens(
    request: Request,
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    ua, ip = _client_meta(request)
    try:
        user, access, refresh = await auth_token_service.rotate_refresh_token(
            db,
            payload.refresh_token,
            user_agent=ua,
            ip_address=ip,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    return TokenPairResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        company_id=user.company_id,
        role=user.role.value if user.role else None,
    )


@router.post(
    "/revoke-refresh",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
@limiter.limit("30/minute")
async def revoke_refresh(
    request: Request,
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    await auth_token_service.revoke_refresh_token(db, payload.refresh_token)
    await db.commit()


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request password reset (email stub)",
)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    email = payload.email.strip().lower()
    user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is not None:
        raw = await auth_token_service.create_password_reset_token(db, user)
        await db.commit()
        email_stub.send_password_reset(email=user.email, reset_token=raw)
    else:
        logger.info("Auth.forgot_password_unknown_email | email={email}", email=email)
    return {"detail": "If the account exists, a reset email was sent."}


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Complete password reset with one-time token",
)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await auth_token_service.reset_password(
            db, raw_token=payload.token, new_password=payload.new_password
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/oauth/{provider}", summary="Social OAuth start (stub)")
async def oauth_start(provider: str) -> dict[str, str]:
    if provider not in {"google", "github"}:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider.")
    if settings.is_production or not bool(getattr(settings, "ALLOW_OAUTH_STUB", False)):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Social OAuth is not configured. Set real OAuth client IDs and "
                "disable the stub callback."
            ),
        )
    return {
        "provider": provider,
        "status": "stub",
        "authorize_url": f"/api/v1/auth/oauth/{provider}/callback",
        "detail": (
            "Dev-only stub. Enable with ALLOW_OAUTH_STUB=true. "
            "Never enable in production — callback trusts client email."
        ),
    }


@router.post(
    "/oauth/callback",
    response_model=TokenPairResponse,
    summary="Social OAuth callback stub (Google/GitHub) — DEV ONLY",
)
@limiter.limit("10/minute")
async def oauth_callback_stub(
    request: Request,
    payload: OAuthStubCallbackRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    if settings.is_production or not bool(getattr(settings, "ALLOW_OAUTH_STUB", False)):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="OAuth stub callback is disabled.",
        )
    email = payload.email.strip().lower()
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            full_name=payload.full_name.strip() or email.split("@")[0],
            company_name=f"{payload.provider.title()} Workspace",
            company_id=user_id,
            role=UserRole.OWNER,
            is_active=True,
            is_verified=True,
            is_superadmin=False,
        )
        db.add(user)
        await db.flush()
        company = await team_service._ensure_primary_company(db, user)
        if not company.slug:
            company.slug = slugify_org_name(company.name)

    await auth_token_service.link_oauth_stub(
        db,
        user,
        provider=payload.provider,
        provider_account_id=payload.provider_account_id,
    )
    ua, ip = _client_meta(request)
    refresh = await auth_token_service.issue_refresh_token(
        db, user, user_agent=ua, ip_address=ip
    )
    await db.commit()
    return TokenPairResponse(
        access_token=mint_user_token(user),
        refresh_token=refresh,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        company_id=user.company_id,
        role=user.role.value if user.role else None,
    )
