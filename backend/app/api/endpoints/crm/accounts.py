"""Native CRM — accounts HTTP API (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.crm.accounts_contacts import (
    CrmAccountCreate,
    CrmAccountListResponse,
    CrmAccountRead,
    CrmAccountUpdate,
)
from app.services.crm.account_service import AccountServiceError, account_service

router = APIRouter(prefix="/crm/accounts", tags=["crm-accounts"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _http_error(exc: AccountServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=CrmAccountListResponse, summary="List CRM accounts")
async def list_accounts(
    q: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmAccountListResponse:
    return await account_service.list_accounts(
        db, _org_id(current_user), q=q, limit=limit, offset=offset
    )


@router.get("/{account_id}", response_model=CrmAccountRead, summary="Get CRM account")
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmAccountRead:
    try:
        return await account_service.get_account(db, _org_id(current_user), account_id)
    except AccountServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=CrmAccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM account",
)
async def create_account(
    payload: CrmAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmAccountRead:
    return await account_service.create_account(db, _org_id(current_user), payload)


@router.patch("/{account_id}", response_model=CrmAccountRead, summary="Update CRM account")
async def update_account(
    account_id: uuid.UUID,
    payload: CrmAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmAccountRead:
    try:
        return await account_service.update_account(
            db, _org_id(current_user), account_id, payload
        )
    except AccountServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM account",
)
async def delete_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await account_service.delete_account(db, _org_id(current_user), account_id)
    except AccountServiceError as exc:
        raise _http_error(exc) from exc
