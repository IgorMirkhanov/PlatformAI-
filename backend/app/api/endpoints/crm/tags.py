"""Native CRM — tags HTTP API (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.crm.tags_fields import (
    CrmTagCreate,
    CrmTagListResponse,
    CrmTagRead,
    CrmTagUpdate,
)
from app.services.crm.tag_service import TagServiceError, tag_service

router = APIRouter(prefix="/crm/tags", tags=["crm-tags"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _http_error(exc: TagServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=CrmTagListResponse, summary="List CRM tags")
async def list_tags(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmTagListResponse:
    return await tag_service.list_tags(
        db, _org_id(current_user), limit=limit, offset=offset
    )


@router.get("/{tag_id}", response_model=CrmTagRead, summary="Get CRM tag")
async def get_tag(
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmTagRead:
    try:
        return await tag_service.get_tag(db, _org_id(current_user), tag_id)
    except TagServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=CrmTagRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM tag",
)
async def create_tag(
    payload: CrmTagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmTagRead:
    try:
        return await tag_service.create_tag(db, _org_id(current_user), payload)
    except TagServiceError as exc:
        raise _http_error(exc) from exc


@router.patch("/{tag_id}", response_model=CrmTagRead, summary="Update CRM tag")
async def update_tag(
    tag_id: uuid.UUID,
    payload: CrmTagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmTagRead:
    try:
        return await tag_service.update_tag(db, _org_id(current_user), tag_id, payload)
    except TagServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM tag",
)
async def delete_tag(
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await tag_service.delete_tag(db, _org_id(current_user), tag_id)
    except TagServiceError as exc:
        raise _http_error(exc) from exc
