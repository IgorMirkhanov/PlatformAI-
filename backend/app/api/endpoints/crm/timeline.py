"""Native CRM — timeline HTTP API (read-only, OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.crm.activities_notes import CrmTimelineListResponse
from app.services.crm.timeline_service import TimelineServiceError, timeline_service

router = APIRouter(prefix="/crm/timeline", tags=["crm-timeline"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


@router.get("", response_model=CrmTimelineListResponse, summary="List CRM timeline events")
async def list_timeline(
    deal_id: uuid.UUID | None = Query(default=None),
    contact_id: uuid.UUID | None = Query(default=None),
    event_type: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmTimelineListResponse:
    try:
        return await timeline_service.get_events(
            db,
            _org_id(current_user),
            deal_id=deal_id,
            contact_id=contact_id,
            event_type=event_type,
            limit=limit,
            offset=offset,
        )
    except TimelineServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
