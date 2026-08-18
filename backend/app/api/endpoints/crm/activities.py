"""Native CRM — activities HTTP API (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.core_models import UserRole
from app.models.crm.activity import ActivityType
from app.models.users import User
from app.schemas.crm.activities_notes import (
    CrmActivityCreate,
    CrmActivityListResponse,
    CrmActivityRead,
    CrmActivityUpdate,
)
from app.services.crm.activity_service import ActivityServiceError, activity_service

router = APIRouter(prefix="/crm/activities", tags=["crm-activities"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _http_error(exc: ActivityServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=CrmActivityListResponse, summary="List CRM activities")
async def list_activities(
    deal_id: uuid.UUID | None = Query(default=None),
    contact_id: uuid.UUID | None = Query(default=None),
    activity_type: ActivityType | None = Query(default=None, alias="type"),
    only_open: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmActivityListResponse:
    return await activity_service.list_activities(
        db,
        _org_id(current_user),
        deal_id=deal_id,
        contact_id=contact_id,
        activity_type=activity_type,
        only_open=only_open,
        limit=limit,
        offset=offset,
    )


@router.get("/{activity_id}", response_model=CrmActivityRead, summary="Get CRM activity")
async def get_activity(
    activity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmActivityRead:
    try:
        return await activity_service.get_activity(db, _org_id(current_user), activity_id)
    except ActivityServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=CrmActivityRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM activity",
)
async def create_activity(
    payload: CrmActivityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmActivityRead:
    try:
        return await activity_service.create_activity(
            db,
            _org_id(current_user),
            payload,
            created_by_id=current_user.id,
        )
    except ActivityServiceError as exc:
        raise _http_error(exc) from exc


@router.patch("/{activity_id}", response_model=CrmActivityRead, summary="Update CRM activity")
async def update_activity(
    activity_id: uuid.UUID,
    payload: CrmActivityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmActivityRead:
    try:
        return await activity_service.update_activity(
            db, _org_id(current_user), activity_id, payload
        )
    except ActivityServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{activity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM activity",
)
async def delete_activity(
    activity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await activity_service.delete_activity(db, _org_id(current_user), activity_id)
    except ActivityServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{activity_id}/complete",
    response_model=CrmActivityRead,
    summary="Mark CRM activity completed",
)
async def complete_activity(
    activity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmActivityRead:
    try:
        return await activity_service.complete_activity(db, _org_id(current_user), activity_id)
    except ActivityServiceError as exc:
        raise _http_error(exc) from exc
