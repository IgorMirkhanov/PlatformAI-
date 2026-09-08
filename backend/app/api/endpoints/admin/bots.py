"""Admin bots inventory (paginated)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_superadmin
from app.api.endpoints.admin.common import (
    ACTION_BOT_BALANCE_ADJUST,
    ACTION_BOT_SUBSCRIPTION,
)
from app.api.endpoints.admin.pagination import (
    AdminPaginatedResponse,
    PaginationParams,
    build_paginated,
)
from app.api.dependencies.admin import ensure_not_impersonated
from app.core.database import get_db
from app.models.core_models import Bot, Company
from app.models.users import User
from app.services.audit_service import audit_service
from app.services.bot_billing_service import (
    BotWalletInsufficientError,
    bot_billing_service,
)

router = APIRouter(tags=["admin-bots"])


class AdminBotItem(BaseModel):
    id: uuid.UUID
    name: str
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    owner_email: str | None = None
    is_active: bool
    subscription_active: bool = False
    subscription_expires_at: datetime | None = None
    wallet_balance: int = 0
    created_at: datetime


class AdminBotListResponse(AdminPaginatedResponse[AdminBotItem]):
    bots: list[AdminBotItem] = Field(default_factory=list)


class AdminBotBalanceAdjustRequest(BaseModel):
    amount_delta: int = Field(..., description="Positive to credit, negative to debit bot credits")
    reason: str = Field(..., min_length=1, max_length=1024)


class AdminBotBalanceAdjustResponse(BaseModel):
    bot_id: uuid.UUID
    bot_name: str
    organization_id: uuid.UUID | None = None
    previous_balance: int
    amount_delta: int
    new_balance: int
    message: str = "Bot balance updated."


class AdminBotSubscriptionRequest(BaseModel):
    active: bool
    expires_at: datetime | None = None
    reason: str = Field(..., min_length=1, max_length=1024)


class AdminBotSubscriptionResponse(BaseModel):
    bot_id: uuid.UUID
    bot_name: str
    subscription_active: bool
    subscription_expires_at: datetime | None = None
    wallet_balance: int
    message: str


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
            subscription_active=bool(getattr(bot, "subscription_active", False)),
            subscription_expires_at=getattr(bot, "subscription_expires_at", None),
            wallet_balance=int(getattr(bot, "wallet_balance", 0) or 0),
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


@router.post(
    "/bots/{bot_id}/balance",
    response_model=AdminBotBalanceAdjustResponse,
    summary="Credit or debit a bot's own credit wallet",
)
async def adjust_bot_balance(
    bot_id: uuid.UUID,
    payload: AdminBotBalanceAdjustRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
    _: User = Depends(ensure_not_impersonated),
) -> AdminBotBalanceAdjustResponse:
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Reason is required.")
    if payload.amount_delta == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="amount_delta must be non-zero.")
    bot = await bot_billing_service.get_bot(db, bot_id)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bot not found.")
    try:
        result = await bot_billing_service.adjust_balance(db, bot_id, int(payload.amount_delta))
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bot not found.") from exc
    except BotWalletInsufficientError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await audit_service.write(
        db,
        admin_id=current_user.id,
        target_user_id=bot.user_id,
        organization_id=bot.organization_id,
        action=ACTION_BOT_BALANCE_ADJUST,
        details=f"bot={bot_id} delta={payload.amount_delta} reason={reason}",
        ip_address=audit_service.client_ip(request),
    )
    await db.commit()
    return AdminBotBalanceAdjustResponse(
        bot_id=result["bot_id"],
        bot_name=bot.name or "",
        organization_id=bot.organization_id,
        previous_balance=int(result["previous_balance"]),
        amount_delta=int(result["amount_delta"]),
        new_balance=int(result["new_balance"]),
        message="Bot balance updated.",
    )


@router.post(
    "/bots/{bot_id}/subscription",
    response_model=AdminBotSubscriptionResponse,
    summary="Enable or disable a bot's chat subscription",
)
async def set_bot_subscription(
    bot_id: uuid.UUID,
    payload: AdminBotSubscriptionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
    _: User = Depends(ensure_not_impersonated),
) -> AdminBotSubscriptionResponse:
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Reason is required.")
    try:
        bot = await bot_billing_service.set_subscription(
            db,
            bot_id,
            active=payload.active,
            expires_at=payload.expires_at,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bot not found.") from exc

    await audit_service.write(
        db,
        admin_id=current_user.id,
        target_user_id=bot.user_id,
        organization_id=bot.organization_id,
        action=ACTION_BOT_SUBSCRIPTION,
        details=f"bot={bot_id} active={payload.active} reason={reason}",
        ip_address=audit_service.client_ip(request),
    )
    await db.commit()
    state = "включена" if bot.subscription_active else "выключена"
    return AdminBotSubscriptionResponse(
        bot_id=bot.id,
        bot_name=bot.name,
        subscription_active=bool(bot.subscription_active),
        subscription_expires_at=bot.subscription_expires_at,
        wallet_balance=int(bot.wallet_balance or 0),
        message=f"Подписка агента {state}.",
    )

