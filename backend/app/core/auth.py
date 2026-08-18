"""OAuth2 password bearer + JWT helpers (fastapi-users compatible surface)."""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import TokenError, create_access_token, decode_access_token, verify_password
from app.core.tenant import get_tenant
from app.models.core_models import Company, UserRole
from app.models.users import User
from app.services.team_service import team_service

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


def slugify_org_name(name: str) -> str:
    base = _SLUG_SAFE.sub("-", name.strip().lower()).strip("-")[:48] or "org"
    return f"{base}-{uuid.uuid4().hex[:6]}"


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(
        select(User).where(
            User.email == email.strip().lower(),
            User.deleted_at.is_(None),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    if not bool(getattr(user, "is_active", True)):
        return None
    return user


def mint_user_token(user: User) -> str:
    return create_access_token(
        subject=user.id,
        company_id=user.company_id,
        role=user.role.value if user.role else None,
        extra_claims={
            "email": user.email,
            "is_superuser": bool(user.is_superadmin),
            "is_superadmin": bool(user.is_superadmin),
            "is_support": bool(getattr(user, "is_support", False)),
        },
    )


async def get_user_from_bearer(
    db: AsyncSession,
    token: str | None,
    *,
    x_company_id: str | None = None,
) -> User | None:
    if not token:
        return None
    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(str(claims["sub"]))
    except (TokenError, KeyError, ValueError):
        return None

    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None or not bool(getattr(user, "is_active", True)):
        return None

    # Prefer explicit workspace header (same as rbac.get_current_user), then
    # TenantMiddleware JWT-bound org, then JWT company claim.
    workspace_id: uuid.UUID | None = None
    if x_company_id:
        try:
            workspace_id = uuid.UUID(x_company_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Company-Id header.",
            ) from exc
    else:
        tenant = get_tenant()
        if tenant and tenant.organization_id:
            workspace_id = tenant.organization_id
        else:
            company_claim = claims.get("company_id")
            if company_claim:
                try:
                    workspace_id = uuid.UUID(str(company_claim))
                except ValueError:
                    workspace_id = None

    if workspace_id is not None and workspace_id != user.company_id:
        try:
            user = await team_service.apply_workspace_context(db, user, workspace_id)
        except ValueError:
            if bool(user.is_superadmin):
                company = await db.get(Company, workspace_id)
                if company is not None:
                    from sqlalchemy.orm.attributes import set_committed_value

                    set_committed_value(user, "company_id", company.id)
                    set_committed_value(user, "company_name", company.name)
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not a member of the requested organization.",
                )
    return user


async def get_current_user_jwt(
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str | None, Depends(oauth2_scheme)],
    x_company_id: Annotated[str | None, Header(alias="X-Company-Id")] = None,
) -> User:
    """Strict JWT auth for /auth/me and protected routes (no demo fallback)."""
    user = await get_user_from_bearer(db, token, x_company_id=x_company_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user_jwt)]
