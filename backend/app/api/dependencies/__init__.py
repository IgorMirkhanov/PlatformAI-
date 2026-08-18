"""Admin API dependency package."""

from app.api.dependencies.admin import (
    PlatformRole,
    ensure_not_impersonated,
    get_current_admin,
    get_current_superadmin_strict,
    impersonated_by_id,
    is_impersonating,
    platform_role_of,
)
from app.api.dependencies.auth import get_current_user

__all__ = [
    "PlatformRole",
    "ensure_not_impersonated",
    "get_current_admin",
    "get_current_superadmin_strict",
    "get_current_user",
    "impersonated_by_id",
    "is_impersonating",
    "platform_role_of",
]
