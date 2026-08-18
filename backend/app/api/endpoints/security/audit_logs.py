"""Tenant-scoped security audit log API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import can_manage_flows, can_manage_settings, get_current_user
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.security.audit_logs import AuditLogListResponse, AuditLogOut
from app.services.security_audit_service import security_audit_service

router = APIRouter(prefix="/security/audit-logs", tags=["security-audit"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _require_audit_reader(user: User) -> User:
    role = user.role or UserRole.OPERATOR
    if can_manage_flows(role) or can_manage_settings(role):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied: manage settings or flows required to view audit logs.",
    )


@router.get(
    "",
    response_model=AuditLogListResponse,
    summary="List security audit logs for the active organization",
)
async def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditLogListResponse:
    """
    Always scoped to the caller's ``company_id``.

    Callers cannot request another organization's logs — the org filter is
    derived from the authenticated user, never from a free-form query param.
    """
    _require_audit_reader(current_user)
    org_id = _org_id(current_user)
    rows = await security_audit_service.list_for_organization(
        db,
        org_id,
        limit=limit,
        offset=offset,
        action=action,
    )
    return AuditLogListResponse(
        items=[AuditLogOut.model_validate(row) for row in rows],
        total=len(rows),
        limit=limit,
        offset=offset,
    )
