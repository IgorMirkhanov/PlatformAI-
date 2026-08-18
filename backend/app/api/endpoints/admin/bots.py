"""Admin bots inventory (paginated)."""

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
from app.models.core_models import Bot, Company
from app.models.users import User

router = APIRouter(tags=["admin-bots"])


class AdminBotItem(BaseModel):
    id: uuid.UUID
    name: str
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    owner_email: str | None = None
    is_active: bool
    created_at: datetime


class AdminBotListResponse(AdminPaginatedResponse[AdminBotItem]):
    bots: list[AdminBotItem] = Field(default_factory=list)


@router.get(
    "/bots",
    response_model=AdminBotListResponse,
    summary="Global bots inventory for Admin Panel",
)
async def list_admin_bots(
    pagination: PaginationParams = Depends(),
    limit: int | None = Query(default=None, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> dict:
    _ = current_user
    if limit is not None and pagination.page == 1 and pagination.page_size == 20:
        pagination.page_size = min(100, limit)

    Owner = aliased(User)
    filters = [Bot.deleted_at.is_(None)]

    if pagination.search:
        pattern = f"%{pagination.search}%"
        filters.append(
            or_(
                Bot.name.ilike(pattern),
                Company.name.ilike(pattern),
                Owner.email.ilike(pattern),
            )
        )
    if pagination.status:
        status = pagination.status.lower()
        if status in {"active", "true", "1", "yes"}:
            filters.append(Bot.is_active.is_(True))
        elif status in {"inactive", "false", "0", "no"}:
            filters.append(Bot.is_active.is_(False))

    if pagination.date_from is not None:
        filters.append(Bot.created_at >= pagination.date_from)
    if pagination.date_to is not None:
        filters.append(Bot.created_at <= pagination.date_to)

    base = (
        select(
            Bot,
            Company.name.label("organization_name"),
            Owner.email.label("owner_email"),
        )
        .outerjoin(Company, Company.id == Bot.organization_id)
        .outerjoin(Owner, Owner.id == Bot.user_id)
        .where(*filters)
    )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = int(await db.scalar(count_stmt) or 0)

    result = await db.execute(
        base.order_by(Bot.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    rows = result.all()
    items = [
        AdminBotItem(
            id=bot.id,
            name=bot.name or "",
            organization_id=bot.organization_id,
            organization_name=org_name,
            owner_email=str(email or "") if email else None,
            is_active=bool(bot.is_active),
            created_at=bot.created_at,
        )
        for bot, org_name, email in rows
    ]
    payload = build_paginated(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    payload["bots"] = items
    return payload
