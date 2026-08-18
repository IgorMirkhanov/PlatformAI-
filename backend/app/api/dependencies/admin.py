"""Platform admin role helpers and request-scoped impersonation flags."""

from __future__ import annotations

import enum
import uuid

from fastapi import Depends, HTTPException, Request, status

from app.core.rbac import get_current_user
from app.models.users import User


class PlatformRole(str, enum.Enum):
    SUPERADMIN = "SUPERADMIN"
    SUPPORT = "SUPPORT"
    USER = "USER"


def is_platform_superadmin(user: User) -> bool:
    """
    Single source of truth for Admin Panel access.

    True when ``is_superadmin`` is set, or the workspace role literally says
    ``superadmin`` (defensive: external seeds / SQL fixtures).
    """
    if bool(getattr(user, "is_superadmin", False)):
        return True
    raw_role = getattr(user, "role", None)
    role_value = getattr(raw_role, "value", raw_role)
    return str(role_value or "").strip().upper() in {"SUPERADMIN", "SUPER_ADMIN"}


def platform_role_of(user: User) -> PlatformRole:
    if is_platform_superadmin(user):
        return PlatformRole.SUPERADMIN
    if bool(getattr(user, "is_support", False)):
        return PlatformRole.SUPPORT
    return PlatformRole.USER


def is_impersonating(user: User | None = None, request: Request | None = None) -> bool:
    if user is not None and bool(getattr(user, "_is_impersonating", False)):
        return True
    if request is not None and bool(getattr(request.state, "is_impersonating", False)):
        return True
    return False


def impersonated_by_id(user: User | None = None, request: Request | None = None) -> uuid.UUID | None:
    if user is not None:
        value = getattr(user, "_impersonated_by", None)
        if isinstance(value, uuid.UUID):
            return value
    if request is not None:
        value = getattr(request.state, "impersonated_by", None)
        if isinstance(value, uuid.UUID):
            return value
    return None


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Gate every ``/api/v1/admin/*`` route on platform superadmin.

    SUPPORT staff no longer qualifies — the Admin Panel is superadmin-only.
    """
    if not is_platform_superadmin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges",
        )
    return current_user


async def get_current_superadmin_strict(
    current_user: User = Depends(get_current_user),
) -> User:
    if not is_platform_superadmin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges",
        )
    return current_user


async def ensure_not_impersonated(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Block billing / destructive admin mutations while a support session is active.
    """
    if is_impersonating(current_user, request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is blocked during impersonation. Exit support mode first.",
        )
    return current_user
