"""Admin LLM usage log browser (paginated)."""

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
from app.models.usage import LLMUsageLog
from app.models.users import User

router = APIRouter(tags=["admin-usage"])


class AdminUsageLogItem(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    organization_name: str | None = None
    bot_id: uuid.UUID | None = None
    bot_name: str | None = None
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    created_at: datetime


class AdminUsageLogListResponse(AdminPaginatedResponse[AdminUsageLogItem]):
    pass


@router.get(
    "/usage-logs",
    response_model=AdminUsageLogListResponse,
    summary="Paginated LLM usage ledger for Admin Panel",
)
async def list_admin_usage_logs(
    pagination: PaginationParams = Depends(),
    model: str | None = Query(default=None, max_length=128),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> dict:
    _ = current_user
    Org = aliased(Company)
    BotAlias = aliased(Bot)

    filters = []
    if pagination.date_from is not None:
        filters.append(LLMUsageLog.created_at >= pagination.date_from)
    if pagination.date_to is not None:
        filters.append(LLMUsageLog.created_at <= pagination.date_to)
    if model:
        filters.append(LLMUsageLog.model.ilike(f"%{model.strip()}%"))
    if pagination.search:
        pattern = f"%{pagination.search}%"
        filters.append(
            or_(
                LLMUsageLog.model.ilike(pattern),
                LLMUsageLog.provider.ilike(pattern),
                Org.name.ilike(pattern),
                BotAlias.name.ilike(pattern),
            )
        )
    if pagination.status:
        # Soft status mapping: expensive | cheap | all — filter by cost bands.
        status = pagination.status.lower()
        if status == "expensive":
            filters.append(LLMUsageLog.cost_usd >= 0.05)
        elif status == "cheap":
            filters.append(LLMUsageLog.cost_usd < 0.05)

    base = (
        select(
            LLMUsageLog,
            Org.name.label("organization_name"),
            BotAlias.name.label("bot_name"),
        )
        .outerjoin(Org, Org.id == LLMUsageLog.org_id)
        .outerjoin(BotAlias, BotAlias.id == LLMUsageLog.bot_id)
    )
    if filters:
        base = base.where(*filters)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = int(await db.scalar(count_stmt) or 0)

    list_stmt = (
        base.order_by(LLMUsageLog.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(list_stmt)
    rows = result.all()
    items = [
        AdminUsageLogItem(
            id=log.id,
            org_id=log.org_id,
            organization_name=org_name,
            bot_id=log.bot_id,
            bot_name=bot_name,
            provider=log.provider,
            model=log.model,
            prompt_tokens=int(log.prompt_tokens or 0),
            completion_tokens=int(log.completion_tokens or 0),
            cost_usd=float(log.cost_usd or 0),
            created_at=log.created_at,
        )
        for log, org_name, bot_name in rows
    ]
    return build_paginated(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
