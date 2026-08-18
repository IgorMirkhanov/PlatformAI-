"""Thin bots listing via tenant-filtered repository (SaaS layout example)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.database import get_db
from app.core.deps import BotRepo, OptionalTenantId
from app.core.rbac import get_current_user
from app.models.core_models import Bot, PlatformType
from app.models.users import User
from app.repositories.bot_repository import bot_repository

router = APIRouter(tags=["bots"])


class BotListItem(BaseModel):
    id: uuid.UUID
    name: str
    platform_type: PlatformType
    organization_id: uuid.UUID | None
    project_id: uuid.UUID | None
    is_active: bool
    created_at: datetime | None = None
    has_published_flow: bool = False
    flow_count: int = 0
    usage_calls: int = 0
    usage_cost_usd: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class BotListResponse(BaseModel):
    items: list[BotListItem]
    total: int = Field(ge=0)


def _to_list_item(
    bot: Bot,
    *,
    usage: dict[str, float | int] | None = None,
) -> BotListItem:
    flows = list(getattr(bot, "flows", None) or [])
    published = any(getattr(flow, "is_published", False) and flow.deleted_at is None for flow in flows)
    usage = usage or {}
    return BotListItem(
        id=bot.id,
        name=bot.name,
        platform_type=bot.platform_type,
        organization_id=bot.organization_id,
        project_id=bot.project_id,
        is_active=bot.is_active,
        created_at=bot.created_at,
        has_published_flow=published,
        flow_count=len(flows),
        usage_calls=int(usage.get("calls", 0) or 0),
        usage_cost_usd=float(usage.get("cost_usd", 0.0) or 0.0),
    )


@router.get(
    "/bots",
    response_model=BotListResponse,
    summary="List bots for the active workspace (eager flows + usage stats)",
)
async def list_bots(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotListResponse:
    """
    ``GET /api/v1/bots`` — tenant-scoped inventory with ``selectinload(flows)``
    and batched LLM usage aggregates (no N+1).
    """
    org_id = getattr(current_user, "company_id", None)
    repo = bot_repository(db, organization_id=org_id)
    bots = await repo.list(limit=200)
    usage_by_bot = await repo.usage_stats_by_bot([bot.id for bot in bots])
    items = [_to_list_item(bot, usage=usage_by_bot.get(bot.id)) for bot in bots]
    return BotListResponse(items=items, total=len(items))


# Legacy SaaS path kept for backward compatibility.
saas_router = APIRouter(prefix="/saas/bots", tags=["bots"])


@saas_router.get("", response_model=list[BotListItem])
async def list_bots_tenant_scoped(
    current_user: CurrentUser,
    bots: BotRepo,
    tenant_id: OptionalTenantId,
) -> list[BotListItem]:
    """
    List bots for the resolved tenant.

    Prefer ``X-Tenant-ID``; falls back to JWT ``company_id``.
    """
    if tenant_id is None and not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant required (X-Tenant-ID or org-scoped JWT).",
        )
    rows = await bots.list(limit=200)
    usage_by_bot = await bots.usage_stats_by_bot([bot.id for bot in rows])
    return [_to_list_item(bot, usage=usage_by_bot.get(bot.id)) for bot in rows]
