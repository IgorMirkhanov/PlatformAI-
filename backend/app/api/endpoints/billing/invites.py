"""Organization email invite HTTP API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import Permission, assert_permission, get_current_user, require_roles
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.billing.invites import (
    AcceptOrganizationInviteRequest,
    AcceptOrganizationInviteResponse,
    OrganizationInviteCreate,
    OrganizationInviteCreated,
    OrganizationInviteListResponse,
)
from app.services.billing.invite_service import InviteServiceError, invite_service

router = APIRouter(prefix="/organizations/invites", tags=["organization-invites"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _http_error(exc: InviteServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "",
    response_model=OrganizationInviteCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization invite",
)
async def create_invite(
    payload: OrganizationInviteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> OrganizationInviteCreated:
    assert_permission(current_user.role or UserRole.OPERATOR, Permission.TEAM_MANAGE)
    try:
        return await invite_service.create_invite(
            db,
            _org_id(current_user),
            email=payload.email,
            role=payload.role,
            inviter_user_id=current_user.id,
        )
    except InviteServiceError as exc:
        raise _http_error(exc) from exc


@router.get(
    "",
    response_model=OrganizationInviteListResponse,
    summary="List active organization invites",
)
async def list_invites(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> OrganizationInviteListResponse:
    assert_permission(current_user.role or UserRole.OPERATOR, Permission.TEAM_MANAGE)
    return await invite_service.list_active_invites(db, _org_id(current_user))


@router.delete(
    "/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke organization invite",
)
async def revoke_invite(
    invite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    assert_permission(current_user.role or UserRole.OPERATOR, Permission.TEAM_MANAGE)
    try:
        await invite_service.revoke_invite(db, _org_id(current_user), invite_id)
    except InviteServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/accept",
    response_model=AcceptOrganizationInviteResponse,
    summary="Accept organization invite (authenticated)",
)
async def accept_invite(
    payload: AcceptOrganizationInviteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AcceptOrganizationInviteResponse:
    try:
        return await invite_service.accept_invite(db, payload.token, current_user)
    except InviteServiceError as exc:
        raise _http_error(exc) from exc
