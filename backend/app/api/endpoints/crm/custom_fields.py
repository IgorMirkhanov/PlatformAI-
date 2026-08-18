"""Native CRM — custom field definitions HTTP API (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.core_models import UserRole
from app.models.crm.custom_field import CrmEntityType
from app.models.users import User
from app.schemas.crm.tags_fields import (
    CrmCustomFieldCreate,
    CrmCustomFieldListResponse,
    CrmCustomFieldRead,
    CrmCustomFieldUpdate,
)
from app.services.crm.custom_field_service import CustomFieldServiceError, custom_field_service

router = APIRouter(prefix="/crm/custom-fields", tags=["crm-custom-fields"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _http_error(exc: CustomFieldServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "",
    response_model=CrmCustomFieldListResponse,
    summary="List CRM custom field definitions",
)
async def list_custom_fields(
    entity_type: CrmEntityType | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmCustomFieldListResponse:
    return await custom_field_service.list_definitions(
        db,
        _org_id(current_user),
        entity_type=entity_type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{field_id}",
    response_model=CrmCustomFieldRead,
    summary="Get CRM custom field definition",
)
async def get_custom_field(
    field_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmCustomFieldRead:
    try:
        return await custom_field_service.get_definition(db, _org_id(current_user), field_id)
    except CustomFieldServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=CrmCustomFieldRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM custom field definition",
)
async def create_custom_field(
    payload: CrmCustomFieldCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmCustomFieldRead:
    try:
        return await custom_field_service.create_definition(db, _org_id(current_user), payload)
    except CustomFieldServiceError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{field_id}",
    response_model=CrmCustomFieldRead,
    summary="Update CRM custom field definition",
)
async def update_custom_field(
    field_id: uuid.UUID,
    payload: CrmCustomFieldUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmCustomFieldRead:
    try:
        return await custom_field_service.update_definition(
            db, _org_id(current_user), field_id, payload
        )
    except CustomFieldServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM custom field definition",
)
async def delete_custom_field(
    field_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await custom_field_service.delete_definition(db, _org_id(current_user), field_id)
    except CustomFieldServiceError as exc:
        raise _http_error(exc) from exc
