"""Auth dependency re-exports for the Admin Panel package layout."""

from __future__ import annotations

from app.core.rbac import get_current_user

__all__ = ["get_current_user"]
