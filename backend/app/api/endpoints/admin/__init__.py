"""Admin Panel API package — modular routers under ``/api/v1/admin``."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.endpoints.admin import audit, billing, bots, dashboard, health, impersonate, llm_models as admin_llm_models, usage_logs, users
from app.api.endpoints.admin.common import (
    decode_impersonation_token,
    mint_impersonation_token,
    mint_legacy_impersonation_token,
)

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(dashboard.router)
router.include_router(users.router)
router.include_router(bots.router)
router.include_router(billing.router)
router.include_router(audit.router)
router.include_router(impersonate.router)
router.include_router(health.router)
router.include_router(usage_logs.router)
router.include_router(admin_llm_models.router)

__all__ = [
    "decode_impersonation_token",
    "mint_impersonation_token",
    "mint_legacy_impersonation_token",
    "router",
]
