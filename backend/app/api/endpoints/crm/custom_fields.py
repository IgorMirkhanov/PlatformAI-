"""Native CRM — custom field definitions HTTP API (org-scoped)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.crm.deps import (
    crm_org_id,
    require_crm_deal_access,
    require_crm_deal_admin,
)
from app.core.database import get_db
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
    ensure_defaults: bool = Query(
        default=True,
        description="Seed starter deal fields once for this organization when none exist.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmCustomFieldListResponse:
    return await custom_field_service.list_definitions(
        db,
        crm_org_id(current_user),
        entity_type=entity_type,
        limit=limit,
        offset=offset,
        ensure_defaults=ensure_defaults,
    )


@router.get(
    "/{field_id}",
    response_model=CrmCustomFieldRead,
    summary="Get CRM custom field definition",
)
async def get_custom_field(
    field_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmCustomFieldRead:
    try:
        return await custom_field_service.get_definition(
            db, crm_org_id(current_user), field_id
        )
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
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmCustomFieldRead:
    try:
        return await custom_field_service.create_definition(
            db, crm_org_id(current_user), payload
        )
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
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmCustomFieldRead:
    try:
        return await custom_field_service.update_definition(
            db, crm_org_id(current_user), field_id, payload
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
    current_user: User = Depends(require_crm_deal_admin),
) -> None:
    try:
        await custom_field_service.delete_definition(
            db, crm_org_id(current_user), field_id
        )
    except CustomFieldServiceError as exc:
        raise _http_error(exc) from exc
