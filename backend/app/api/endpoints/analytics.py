"""Org analytics / usage meters (UsageEvent aggregates)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.services.analytics_service import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/org/{organization_id}/summary")
async def org_usage_summary(
    organization_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Message / token / cost rollup for a tenant (last N days)."""
    if (
        not current_user.is_superadmin
        and current_user.company_id != organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization.",
        )
    return await analytics_service.org_summary(
        db, organization_id=organization_id, days=days
    )
