"""Organization SQL DB connection management API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import can_manage_flows, can_manage_settings, get_current_user
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.integrations.db_connections import (
    DbConnectionCreate,
    DbConnectionListResponse,
    DbConnectionOut,
)
from app.services.integrations.db_connection_service import (
    DbConnectionServiceError,
    db_connection_service,
)

router = APIRouter(
    prefix="/integrations/db-connections",
    tags=["integrations-db-connections"],
)


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _require_connection_manager(user: User) -> User:
    role = user.role or UserRole.OPERATOR
    if can_manage_flows(role) or can_manage_settings(role):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied: can_manage_settings or can_manage_flows required.",
    )


def _http_error(exc: DbConnectionServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "",
    response_model=DbConnectionListResponse,
    summary="List organization SQL DB connections (metadata only)",
)
async def list_db_connections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DbConnectionListResponse:
    _require_connection_manager(current_user)
    return await db_connection_service.list_connections(db, _org_id(current_user))


@router.post(
    "",
    response_model=DbConnectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create encrypted SQL DB connection",
)
async def create_db_connection(
    payload: DbConnectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DbConnectionOut:
    _require_connection_manager(current_user)
    try:
        return await db_connection_service.create_connection(
            db,
            _org_id(current_user),
            payload,
            created_by_id=current_user.id,
        )
    except DbConnectionServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete SQL DB connection",
)
async def delete_db_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _require_connection_manager(current_user)
    try:
        await db_connection_service.delete_connection(
            db,
            _org_id(current_user),
            connection_id,
        )
    except DbConnectionServiceError as exc:
        raise _http_error(exc) from exc
