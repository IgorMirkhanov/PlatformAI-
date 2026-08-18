"""Admin audit log browser (paginated + searchable)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_superadmin
from app.api.endpoints.admin.pagination import (
    AdminPaginatedResponse,
    PaginationParams,
    build_paginated,
)
from app.core.database import get_db
from app.models.admin_audit import AdminAuditLog
from app.models.core_models import Company
from app.models.users import User

router = APIRouter(tags=["admin-audit"])


class AdminAuditItem(BaseModel):
    id: uuid.UUID
    admin_id: uuid.UUID
    admin_email: str | None = None
    target_user_id: uuid.UUID
    target_email: str | None = None
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    action: str
    details: str | None = None
    ip_address: str | None = None
    created_at: datetime


class AdminAuditListResponse(AdminPaginatedResponse[AdminAuditItem]):
    """Paginated audit trail. Also exposes ``entries`` for older clients."""

    entries: list[AdminAuditItem] = Field(default_factory=list)


async def _list_audit(
    *,
    pagination: PaginationParams,
    action: str | None,
    db: AsyncSession,
) -> dict:
    AdminUser = aliased(User)
    TargetUser = aliased(User)
    Org = aliased(Company)

    filters = []
    if action:
        filters.append(AdminAuditLog.action == action.strip())
    elif pagination.status:
        # status alias for action filter (frontend convenience)
        filters.append(AdminAuditLog.action == pagination.status)

    if pagination.date_from is not None:
        filters.append(AdminAuditLog.created_at >= pagination.date_from)
    if pagination.date_to is not None:
        filters.append(AdminAuditLog.created_at <= pagination.date_to)

    if pagination.search:
        pattern = f"%{pagination.search}%"
        filters.append(
            or_(
                AdminUser.email.ilike(pattern),
                TargetUser.email.ilike(pattern),
                Org.name.ilike(pattern),
                AdminAuditLog.action.ilike(pattern),
                AdminAuditLog.details.ilike(pattern),
                AdminAuditLog.ip_address.ilike(pattern),
            )
        )

    # Single query with FK user + org joins — no per-row secondary lookups.
    base = (
        select(
            AdminAuditLog,
            AdminUser.email.label("admin_email"),
            TargetUser.email.label("target_email"),
            Org.name.label("organization_name"),
        )
        .outerjoin(AdminUser, AdminUser.id == AdminAuditLog.admin_id)
        .outerjoin(TargetUser, TargetUser.id == AdminAuditLog.target_user_id)
        .outerjoin(Org, Org.id == AdminAuditLog.organization_id)
    )
    if filters:
        base = base.where(*filters)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = int(await db.scalar(count_stmt) or 0)

    result = await db.execute(
        base.order_by(AdminAuditLog.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    rows = result.all()
    items = [
        AdminAuditItem(
            id=entry.id,
            admin_id=entry.admin_id,
            admin_email=admin_email,
            target_user_id=entry.target_user_id,
            target_email=target_email,
            organization_id=entry.organization_id,
            organization_name=organization_name,
            action=entry.action,
            details=entry.details,
            ip_address=entry.ip_address,
            created_at=entry.created_at,
        )
        for entry, admin_email, target_email, organization_name in rows
    ]
    payload = build_paginated(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    payload["entries"] = items
    return payload


@router.get(
    "/audit",
    response_model=AdminAuditListResponse,
    summary="Browse AdminAuditLog entries (impersonation, balance adjusts, …)",
)
@router.get(
    "/audit-logs",
    response_model=AdminAuditListResponse,
    summary="Alias for /audit with server-side pagination",
    include_in_schema=True,
)
async def list_admin_audit(
    pagination: PaginationParams = Depends(),
    action: str | None = Query(default=None, max_length=64),
    # Legacy query params
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> dict:
    _ = current_user
    # Honor legacy limit/offset when page not customized beyond defaults
    if limit is not None and pagination.page == 1 and pagination.page_size == 20:
        pagination.page_size = min(100, limit)
        if offset is not None:
            pagination.page = (offset // pagination.page_size) + 1
            pagination.offset = offset
    return await _list_audit(pagination=pagination, action=action, db=db)
