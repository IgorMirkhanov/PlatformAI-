"""FastAPI dependency injection for auth, workspace, and bot access control."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.database import get_db
from app.core.rbac import Permission, assert_permission, get_current_user, has_permission
from app.models.core_models import Bot, Company, UserCompanyWorkspace, UserRole
from app.models.users import User
from app.services.team_service import team_service

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_superadmin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Restrict access to platform superadmins only.

    Raises HTTP 403 with a stable detail string when ``is_superadmin`` is false.
    """
    if not bool(getattr(current_user, "is_superadmin", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges",
        )
    return current_user


CurrentSuperadmin = Annotated[User, Depends(get_current_superadmin)]


async def require_authenticated_user(current_user: CurrentUser) -> User:
    """Ensure a resolved authenticated user is present."""
    if current_user is None or getattr(current_user, "id", None) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return current_user


async def require_workspace_member(
    db: DbSession,
    current_user: CurrentUser,
    company_id: uuid.UUID | None = None,
) -> User:
    """
    Ensure the caller belongs to the active (or explicitly requested) organization.

    Applies workspace role context onto ``current_user`` when a membership row exists.
    Superadmins may enter any organization.

    Regular users cannot bind to an arbitrary ``company_id`` from client headers
    unless they are a verified member of that workspace.
    """
    from app.core.tenant import get_tenant

    tenant = get_tenant()
    # Prefer explicit argument, then verified user workspace, never raw spoofed tenant
    # unless middleware allowed an internal/superadmin override.
    if company_id is None:
        if (
            tenant
            and tenant.organization_id is not None
            and (
                bool(getattr(current_user, "is_superadmin", False))
                or getattr(tenant, "header_override_allowed", False)
                or tenant.source in {"jwt", "subdomain", "internal", "superadmin_header"}
            )
        ):
            # For regular users, tenant.organization_id must match JWT-bound company
            # or a membership-checked switch already applied on current_user.
            if bool(getattr(current_user, "is_superadmin", False)) or getattr(
                tenant, "header_override_allowed", False
            ):
                company_id = tenant.organization_id
            elif tenant.organization_id == getattr(current_user, "company_id", None):
                company_id = tenant.organization_id

    target_company_id = company_id or getattr(current_user, "company_id", None)
    if target_company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active workspace selected.",
        )

    if bool(getattr(current_user, "is_superadmin", False) or getattr(current_user, "is_admin", False)):
        company = await db.get(Company, target_company_id)
        if company is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found.",
            )
        current_user.company_id = company.id
        current_user.company_name = company.name
        return current_user

    try:
        return await team_service.apply_workspace_context(db, current_user, target_company_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc) or "Workspace membership required.",
        ) from exc


async def _bot_accessible_in_workspace(
    db: AsyncSession,
    *,
    user: User,
    bot: Bot,
) -> bool:
    """Return True when the user may operate on the bot within their organization.

    Expects ``bot.user`` (and ideally ``bot.organization``) to already be loaded via
    ``joinedload`` from ``get_bot_for_workspace`` to avoid N+1 lookups.
    """
    if bool(getattr(user, "is_superadmin", False) or getattr(user, "is_admin", False)):
        return True

    if bot.user_id == user.id:
        return True

    workspace_id = getattr(user, "company_id", None)
    if workspace_id is None:
        return False

    owner = bot.user
    if owner is None:
        return False

    # One query covers caller + owner membership in the active workspace.
    membership_rows = await db.execute(
        select(UserCompanyWorkspace.user_id).where(
            UserCompanyWorkspace.company_id == workspace_id,
            UserCompanyWorkspace.user_id.in_((user.id, bot.user_id)),
        )
    )
    member_ids = set(membership_rows.scalars().all())

    # Caller must be a member of the active workspace.
    if user.id not in member_ids and user.id != workspace_id:
        # Soft-launch: personal company_id == user.id without a membership row yet.
        if user.company_id != user.id:
            return False

    if owner.company_id == workspace_id or owner.id == workspace_id:
        return True

    # Bot shares the caller's org via organization_id (when set).
    if bot.organization_id is not None and bot.organization_id == workspace_id:
        return True

    return bot.user_id in member_ids


async def get_bot_for_workspace(
    bot_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> Bot:
    """Load a bot (with owner + organization) and enforce workspace ownership."""
    result = await db.execute(
        select(Bot)
        .where(Bot.id == bot_id, Bot.deleted_at.is_(None))
        .options(
            joinedload(Bot.user),
            joinedload(Bot.organization),
        )
    )
    bot = result.unique().scalar_one_or_none()
    if bot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found.")

    # Normalize workspace context when possible.
    if getattr(current_user, "company_id", None) is not None:
        try:
            await require_workspace_member(db, current_user, current_user.company_id)
        except HTTPException:
            # Superadmin / soft-launch paths still go through accessibility check below.
            pass

    if not await _bot_accessible_in_workspace(db, user=current_user, bot=bot):
        logger.warning(
            "Deps.bot_access_denied | user_id={user_id} bot_id={bot_id} company_id={company_id}",
            user_id=current_user.id,
            bot_id=bot.id,
            company_id=getattr(current_user, "company_id", None),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this bot in the current workspace.",
        )
    return bot


def require_bot_access(
    permission: Permission | None = None,
) -> Callable[..., Bot]:
    """
    Dependency factory: resolve ``bot_id`` path param, verify workspace access,
    and optionally enforce an RBAC permission (flows / credentials).
    """

    async def dependency(
        bot_id: uuid.UUID = Path(..., description="Bot UUID"),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> Bot:
        if permission is not None:
            assert_permission(current_user.role or UserRole.OPERATOR, permission)
        return await get_bot_for_workspace(bot_id=bot_id, db=db, current_user=current_user)

    return dependency


def require_flow_access() -> Callable[..., Bot]:
    """Protect visual flow builder / publish endpoints."""
    return require_bot_access(Permission.FLOW_WRITE)


def require_credential_access() -> Callable[..., Bot]:
    """Protect channel credential connect / disconnect endpoints."""
    return require_bot_access(Permission.BOT_CHANNELS)


async def assert_bot_permission(
    *,
    current_user: User,
    bot: Bot,
    permission: Permission,
    db: AsyncSession,
) -> None:
    """Imperative helper for services that already hold a bot instance."""
    if not await _bot_accessible_in_workspace(db, user=current_user, bot=bot):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this bot in the current workspace.",
        )
    role = current_user.role or UserRole.OPERATOR
    if not has_permission(role, permission):
        assert_permission(role, permission)
