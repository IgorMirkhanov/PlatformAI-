"""Native CRM — API key management (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.crm.deps import crm_org_id, require_crm_deal_admin
from app.core.database import get_db
from app.models.users import User
from app.schemas.crm.api_keys import (
    CrmApiKeyCreate,
    CrmApiKeyCreated,
    CrmApiKeyListResponse,
)
from app.services.crm.api_key_service import ApiKeyServiceError, api_key_service

router = APIRouter(prefix="/crm/api-keys", tags=["crm-api-keys"])


def _http_error(exc: ApiKeyServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=CrmApiKeyListResponse, summary="List CRM API keys")
async def list_api_keys(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmApiKeyListResponse:
    return await api_key_service.list_keys(
        db,
        crm_org_id(current_user),
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=CrmApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM API key (raw secret returned once)",
)
async def create_api_key(
    payload: CrmApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmApiKeyCreated:
    try:
        return await api_key_service.create_api_key(
            db,
            crm_org_id(current_user),
            payload,
            created_by_id=current_user.id,
        )
    except ApiKeyServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM API key",
)
async def delete_api_key(
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> None:
    try:
        await api_key_service.delete_api_key(
            db,
            crm_org_id(current_user),
            key_id,
            actor_user_id=current_user.id,
            ip_address=request.client.host if request.client else None,
        )
    except ApiKeyServiceError as exc:
        raise _http_error(exc) from exc
