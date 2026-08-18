"""Auth routes — OAuth2 password + JWT (fastapi-users compatible contract)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    CurrentUser,
    authenticate_user,
    mint_user_token,
    slugify_org_name,
)
from app.core.config import is_seeded_superadmin_email, settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.models.core_models import Project, UserCompanyWorkspace, UserRole
from app.models.users import User
from app.schemas.auth import (
    LoginJSONRequest,
    LogoutRequest,
    TokenPairResponse,
    TokenResponse,
    UserRead,
    UserRegisterRequest,
)
from app.services.team_service import team_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=mint_user_token(user),
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        company_id=user.company_id,
        role=user.role.value if user.role else None,
    )


async def _token_pair(
    request: Request,
    db: AsyncSession,
    user: User,
) -> TokenPairResponse:
    from app.services.auth_token_service import auth_token_service

    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
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


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user + default Organization/Project",
)
@limiter.limit("3/hour")
async def register(
    request: Request,
    payload: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    email = payload.email.strip().lower()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    user_id = uuid.uuid4()
    # Platform owner accounts get Admin Panel rights on their very first login,
    # without waiting for the next seed run.
    seeded_superadmin = is_seeded_superadmin_email(email)
    user = User(
        id=user_id,
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name.strip() or email.split("@")[0],
        company_name=payload.company_name.strip() or "My Organization",
        company_id=user_id,
        role=UserRole.OWNER,
        is_active=True,
        is_verified=False,
        is_superadmin=seeded_superadmin,
    )
    db.add(user)
    await db.flush()

    company = await team_service._ensure_primary_company(db, user)
    if not company.slug:
        company.slug = slugify_org_name(company.name)

    membership = await db.scalar(
        select(UserCompanyWorkspace).where(
            UserCompanyWorkspace.user_id == user.id,
            UserCompanyWorkspace.company_id == company.id,
        )
    )
    if membership is None:
        db.add(
            UserCompanyWorkspace(
                user_id=user.id,
                company_id=company.id,
                role=UserRole.OWNER,
            )
        )

    default_project = await db.scalar(
        select(Project).where(
            Project.organization_id == company.id,
            Project.slug == "default",
        )
    )
    if default_project is None:
        db.add(
            Project(
                organization_id=company.id,
                name="Default",
                slug="default",
                description="Default project",
            )
        )

    # Seed OrganizationWallet with Free-tier starter credits so new tenants can
    # exercise Sandbox / LLM without a separate top-up step.
    from app.services.billing.wallet_service import wallet_service

    starter = max(0, int(getattr(settings, "REGISTER_WALLET_STARTER_CREDITS", 0) or 0))
    await wallet_service.get_or_create_wallet(
        db, company.id, initial_balance=starter
    )

    await db.flush()
    await db.refresh(user)
    logger.info(
        "Auth.register_ok | user_id={user_id} org_id={org_id} starter_credits={credits} "
        "superadmin={superadmin}",
        user_id=user.id,
        org_id=company.id,
        credits=starter,
        superadmin=seeded_superadmin,
    )
    return user


@router.post(
    "/login",
    response_model=TokenPairResponse,
    summary="OAuth2 password login (form) → JWT + refresh",
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    user = await authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await team_service._ensure_primary_company(db, user)
    logger.info("Auth.login_ok | user_id={user_id}", user_id=user.id)
    return await _token_pair(request, db, user)


@router.post(
    "/login/json",
    response_model=TokenPairResponse,
    summary="JSON body login → JWT + refresh (SPA convenience)",
)
@limiter.limit("5/minute")
async def login_json(
    request: Request,
    payload: LoginJSONRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenPairResponse:
    user = await authenticate_user(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await team_service._ensure_primary_company(db, user)
    return await _token_pair(request, db, user)


@router.get("/me", response_model=UserRead, summary="Current authenticated user")
async def me(current_user: CurrentUser) -> User:
    return current_user


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke refresh token(s) and end server session",
)
async def logout(
    current_user: CurrentUser,
    payload: LogoutRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> None:
    from app.services.auth_token_service import auth_token_service

    if payload and payload.refresh_token:
        await auth_token_service.revoke_refresh_token(db, payload.refresh_token)
    else:
        await auth_token_service.revoke_all_refresh_tokens(db, current_user.id)
    await db.commit()
    logger.info("Auth.logout | user_id={user_id}", user_id=current_user.id)
    return None
