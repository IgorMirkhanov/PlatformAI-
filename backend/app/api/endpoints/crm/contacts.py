"""Native CRM — contacts HTTP API (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.crm.accounts_contacts import (
    CrmContactCreate,
    CrmContactListResponse,
    CrmContactRead,
    CrmContactUpdate,
)
from app.services.crm.contact_service import ContactServiceError, contact_service

router = APIRouter(prefix="/crm/contacts", tags=["crm-contacts"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _http_error(exc: ContactServiceError) -> HTTPException:
    if exc.status_code == status.HTTP_402_PAYMENT_REQUIRED:
        return HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "crm_contacts_limit",
                "message": exc.message,
                "billing_url": "/billing",
            },
        )
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=CrmContactListResponse, summary="List CRM contacts")
async def list_contacts(
    q: str | None = Query(default=None, max_length=255),
    account_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmContactListResponse:
    return await contact_service.list_contacts(
        db,
        _org_id(current_user),
        q=q,
        account_id=account_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{contact_id}", response_model=CrmContactRead, summary="Get CRM contact")
async def get_contact(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmContactRead:
    try:
        return await contact_service.get_contact(db, _org_id(current_user), contact_id)
    except ContactServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=CrmContactRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM contact",
)
async def create_contact(
    payload: CrmContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmContactRead:
    try:
        return await contact_service.create_contact(db, _org_id(current_user), payload)
    except ContactServiceError as exc:
        raise _http_error(exc) from exc


@router.patch("/{contact_id}", response_model=CrmContactRead, summary="Update CRM contact")
async def update_contact(
    contact_id: uuid.UUID,
    payload: CrmContactUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmContactRead:
    try:
        return await contact_service.update_contact(
            db, _org_id(current_user), contact_id, payload
        )
    except ContactServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM contact",
)
async def delete_contact(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await contact_service.delete_contact(db, _org_id(current_user), contact_id)
    except ContactServiceError as exc:
        raise _http_error(exc) from exc
