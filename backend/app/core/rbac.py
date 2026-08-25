from __future__ import annotations

import uuid
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any

from fastapi import Depends, Header, HTTPException, Query, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.models.core_models import Company, UserCompanyWorkspace, UserRole
from app.models.users import User
from app.services.team_service import team_service


class Permission(str, Enum):
    BILLING_READ = "billing:read"
    BILLING_WRITE = "billing:write"
    TEAM_MANAGE = "team:manage"
    BOT_PROMPTING = "bot:prompting"
    BOT_CHANNELS = "bot:channels"
    BOT_SETTINGS = "bot:settings"
    BOT_KNOWLEDGE = "bot:knowledge"
    BOT_LLM = "bot:llm"
    BOT_FUNCTIONS = "bot:functions"
    BOT_INTEGRATIONS = "bot:integrations"
    BOT_MESSAGES = "bot:messages"
    INBOX_READ = "inbox:read"
    DASHBOARD_READ = "dashboard:read"
    FLOW_WRITE = "flow:write"
    # Workspace section gates (Step 0.2 matrix)
    MANAGE_BILLING = "manage:billing"
    MANAGE_FLOWS = "manage:flows"
    MANAGE_CRM = "manage:crm"
    MANAGE_SETTINGS = "manage:settings"


ALL_PERMISSIONS = frozenset(Permission)

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.OWNER: ALL_PERMISSIONS,
    UserRole.ADMIN: frozenset(
        {
            Permission.BILLING_READ,
            Permission.BILLING_WRITE,
            Permission.TEAM_MANAGE,
            Permission.BOT_PROMPTING,
            Permission.BOT_CHANNELS,
            Permission.BOT_SETTINGS,
            Permission.BOT_KNOWLEDGE,
            Permission.BOT_LLM,
            Permission.BOT_FUNCTIONS,
            Permission.BOT_INTEGRATIONS,
            Permission.BOT_MESSAGES,
            Permission.INBOX_READ,
            Permission.DASHBOARD_READ,
            Permission.FLOW_WRITE,
            Permission.MANAGE_BILLING,
            Permission.MANAGE_FLOWS,
            Permission.MANAGE_CRM,
            Permission.MANAGE_SETTINGS,
        }
    ),
    UserRole.MEMBER: frozenset(
        {
            Permission.BOT_PROMPTING,
            Permission.BOT_KNOWLEDGE,
            Permission.BOT_LLM,
            Permission.BOT_FUNCTIONS,
            Permission.BOT_MESSAGES,
            Permission.INBOX_READ,
            Permission.DASHBOARD_READ,
            Permission.FLOW_WRITE,
            Permission.MANAGE_FLOWS,
        }
    ),
    UserRole.PROMPT_ENGINEER: frozenset(
        {
            Permission.BOT_PROMPTING,
            Permission.BOT_KNOWLEDGE,
            Permission.BOT_LLM,
            Permission.BOT_FUNCTIONS,
            Permission.BOT_MESSAGES,
            Permission.BOT_SETTINGS,
            Permission.INBOX_READ,
            Permission.DASHBOARD_READ,
            Permission.FLOW_WRITE,
            Permission.MANAGE_FLOWS,
        }
    ),
    UserRole.OPERATOR: frozenset(
        {
            Permission.INBOX_READ,
            Permission.DASHBOARD_READ,
            Permission.MANAGE_CRM,
        }
    ),
}


def has_permission(role: UserRole, permission: Permission) -> bool:
    allowed = ROLE_PERMISSIONS.get(role, frozenset())
    return permission in allowed


def assert_permission(role: UserRole, permission: Permission) -> None:
    if not has_permission(role, permission):
        logger.warning(
            "RBAC.denied | role={role} permission={permission}",
            role=role.value,
            permission=permission.value,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role.value}' is not allowed to perform '{permission.value}'.",
        )


def can_manage_billing(role: UserRole) -> bool:
    """Billing section — OWNER / ADMIN only."""
    return has_permission(role, Permission.MANAGE_BILLING)


def can_manage_flows(role: UserRole) -> bool:
    """Flow builder — OWNER / ADMIN / MEMBER (+ legacy PROMPT_ENGINEER)."""
    return has_permission(role, Permission.MANAGE_FLOWS)


def can_manage_crm(role: UserRole) -> bool:
    """Native CRM — OWNER / ADMIN / OPERATOR."""
    return has_permission(role, Permission.MANAGE_CRM)


def can_manage_settings(role: UserRole) -> bool:
    """Org settings — OWNER / ADMIN only."""
    return has_permission(role, Permission.MANAGE_SETTINGS)


async def ensure_demo_user(db: AsyncSession) -> User:
    if settings.is_production:
        raise RuntimeError("ensure_demo_user must not be called in production.")
    result = await db.execute(select(User).limit(1))
    user = result.scalar_one_or_none()
    if user is not None:
        if user.company_id is None:
            user.company_id = user.id
        if user.role is None:
            user.role = UserRole.OWNER
        await team_service._ensure_primary_company(db, user)
        await db.flush()
        return user

    user = User(
        email="admin@mp.ai",
        hashed_password="!",
        company_name="MP.AI Production Console",
        full_name="Workspace Owner",
        role=UserRole.OWNER,
    )
    db.add(user)
    await db.flush()
    if user.company_id != user.id:
        user.company_id = user.id
        await db.flush()
    await team_service._ensure_primary_company(db, user)
    await db.flush()
    logger.info("RBAC.demo_user_created | user_id={user_id}", user_id=user.id)
    return user


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    user_id: uuid.UUID | None = Query(default=None),
) -> User:
    """
    Resolve the authenticated user.

    Priority:
      1. ``Authorization: Bearer imp_*`` — ephemeral admin impersonation
      2. ``Authorization: Bearer <JWT>`` — standard HS256 access token (no prefix)
      3. ``X-User-Id`` / ``user_id`` query — soft-launch / local tooling
      4. Demo bootstrap user (development only)
    """
    jwt_company_id: uuid.UUID | None = None

    if authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization.split(" ", 1)[1].strip()

        # Ephemeral superadmin impersonation tokens.
        if raw_token.startswith("imp_"):
            from app.api.endpoints.admin import decode_impersonation_token
            from app.core.redis_client import (
                impersonation_token_fingerprint,
                is_impersonation_jti_revoked,
            )

            if is_impersonation_jti_revoked(impersonation_token_fingerprint(raw_token)):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Impersonation token has been revoked.",
                )

            payload = decode_impersonation_token(raw_token)
            if payload is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired impersonation token.",
                )
            try:
                target_id = uuid.UUID(str(payload["target_user_id"]))
                company_id = uuid.UUID(str(payload["organization_id"]))
            except (KeyError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Malformed impersonation token.",
                ) from exc

            result = await db.execute(
                select(User).where(User.id == target_id, User.deleted_at.is_(None))
            )
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
            try:
                setattr(user, "_impersonated_by", uuid.UUID(str(payload.get("impersonated_by") or payload["actor_user_id"])))
                setattr(user, "_is_impersonating", True)
            except (KeyError, ValueError):
                setattr(user, "_is_impersonating", True)
            try:
                return await team_service.apply_workspace_context(db, user, company_id)
            except ValueError:
                company = await db.get(Company, company_id)
                if company is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Organization not found.",
                    )
                user.company_id = company.id
                user.company_name = company.name
                user.role = UserRole.OWNER
                return user

        # Standard JWT (access or impersonation).
        from app.core.security import TokenError, decode_access_token

        try:
            claims = decode_access_token(raw_token)
            target_id = uuid.UUID(str(claims["sub"]))
        except (TokenError, KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc) if isinstance(exc, TokenError) else "Invalid access token.",
            ) from exc

        result = await db.execute(
            select(User).where(User.id == target_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        if not bool(getattr(user, "is_active", True)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled.",
            )

        # Mark support impersonation session on the user object (request-scoped).
        if claims.get("typ") == "impersonation":
            from app.core.redis_client import (
                impersonation_token_fingerprint,
                is_impersonation_jti_revoked,
            )

            jti = str(claims.get("jti") or "").strip() or impersonation_token_fingerprint(
                raw_token
            )
            if is_impersonation_jti_revoked(jti):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Impersonation token has been revoked.",
                )

            impersonated_by_raw = claims.get("impersonated_by")
            if not impersonated_by_raw:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Malformed impersonation token.",
                )
            try:
                setattr(user, "_impersonated_by", uuid.UUID(str(impersonated_by_raw)))
                setattr(user, "_is_impersonating", True)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Malformed impersonated_by claim.",
                ) from exc

        company_claim = claims.get("company_id")
        if company_claim:
            try:
                jwt_company_id = uuid.UUID(str(company_claim))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Malformed company_id claim in access token.",
                ) from exc

        role_claim = claims.get("role")
        if role_claim and user.role is None:
            try:
                user.role = UserRole(str(role_claim))
            except ValueError:
                pass

        # Prefer explicit workspace header, then JWT company claim.
        workspace_id = None
        if x_company_id:
            try:
                workspace_id = uuid.UUID(x_company_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid X-Company-Id header.",
                ) from exc
        elif jwt_company_id is not None:
            workspace_id = jwt_company_id

        if workspace_id is not None:
            try:
                return await team_service.apply_workspace_context(db, user, workspace_id)
            except ValueError as exc:
                if bool(getattr(user, "is_superadmin", False)):
                    company = await db.get(Company, workspace_id)
                    if company is None:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Organization not found.",
                        ) from exc
                    from sqlalchemy.orm.attributes import set_committed_value

                    set_committed_value(user, "company_id", company.id)
                    set_committed_value(user, "company_name", company.name)
                    return user
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(exc),
                ) from exc

        return user

    # Soft-launch identity shortcuts — never in production; default OFF.
    if settings.is_production or not bool(getattr(settings, "ALLOW_SOFT_LAUNCH_AUTH", False)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    target_id: uuid.UUID | None = None
    if x_user_id:
        try:
            target_id = uuid.UUID(x_user_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-User-Id header.",
            ) from exc
    elif user_id is not None:
        target_id = user_id

    if target_id is not None:
        result = await db.execute(
            select(User).where(User.id == target_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    else:
        user = await ensure_demo_user(db)

    if x_company_id:
        try:
            company_id = uuid.UUID(x_company_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Company-Id header.",
            ) from exc
        try:
            user = await team_service.apply_workspace_context(db, user, company_id)
        except ValueError as exc:
            if bool(getattr(user, "is_superadmin", False)):
                company = await db.get(Company, company_id)
                if company is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Organization not found.",
                    ) from exc
                user.company_id = company.id
                user.company_name = company.name
            else:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return user


def require_roles(*roles: UserRole) -> Callable[..., Any]:
    allowed_roles = frozenset(roles)

    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            logger.warning(
                "RBAC.role_denied | user_id={user_id} role={role} required={required}",
                user_id=current_user.id,
                role=current_user.role.value,
                required=[role.value for role in roles],
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role privileges for this action.",
            )
        return current_user

    return dependency


def require_permission(permission: Permission) -> Callable[..., Any]:
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        assert_permission(current_user.role, permission)
        return current_user

    return dependency


def require_roles_decorator(*roles: UserRole) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    allowed_roles = frozenset(roles)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_user: User | None = kwargs.get("current_user")
            if current_user is None:
                for value in kwargs.values():
                    if isinstance(value, User):
                        current_user = value
                        break
            if current_user is None or current_user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient role privileges for this action.",
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
