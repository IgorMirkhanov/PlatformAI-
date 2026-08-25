"""Organization token wallet — balance, ledger, usage-by-bot."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import Permission, get_current_user, require_permission
from app.models.users import User
from app.repositories.wallet_repository import wallet_repository
from app.services.billing.wallet_service import wallet_service as credit_wallet

router = APIRouter(prefix="/wallet", tags=["wallet"])


class WalletTransactionRead(BaseModel):
    id: uuid.UUID
    tx_type: str
    amount_tokens: int
    balance_after: int
    bot_id: uuid.UUID | None = None
    model_used: str | None = None
    created_at: datetime


class WalletOverviewResponse(BaseModel):
    organization_id: uuid.UUID
    balance_tokens: int
    credit_balance: int
    status: str
    low_balance_threshold: int
    blocked_at: datetime | None = None
    transactions: list[WalletTransactionRead]


class BotUsageRow(BaseModel):
    bot_id: uuid.UUID | None = None
    amount_tokens: int


class WalletUsageByBotResponse(BaseModel):
    organization_id: uuid.UUID
    days: int
    items: list[BotUsageRow]


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


@router.get("", response_model=WalletOverviewResponse, summary="Token wallet + last 20 ledger rows")
async def get_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_READ)),
) -> WalletOverviewResponse:
    org_id = _org_id(current_user)
    wallet = await credit_wallet.get_or_create_wallet(db, org_id)
    rows = await wallet_repository(db).list_recent(org_id, limit=20)
    return WalletOverviewResponse(
        organization_id=org_id,
        balance_tokens=int(getattr(wallet, "balance_tokens", 0) or 0),
        credit_balance=int(wallet.balance),
        status=str(getattr(wallet, "status", "active") or "active"),
        low_balance_threshold=int(getattr(wallet, "low_balance_threshold", 1000) or 1000),
        blocked_at=getattr(wallet, "blocked_at", None),
        transactions=[
            WalletTransactionRead(
                id=row.id,
                tx_type=row.tx_type,
                amount_tokens=int(row.amount_tokens),
                balance_after=int(row.balance_after),
                bot_id=row.bot_id,
                model_used=row.model_used,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


@router.get(
    "/usage-by-bot",
    response_model=WalletUsageByBotResponse,
    summary="Token spend grouped by bot",
)
async def get_usage_by_bot(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_READ)),
) -> WalletUsageByBotResponse:
    org_id = _org_id(current_user)
    items = await wallet_repository(db).usage_by_bot(org_id, days=days)
    return WalletUsageByBotResponse(
        organization_id=org_id,
        days=days,
        items=[BotUsageRow(bot_id=bot_id, amount_tokens=amount) for bot_id, amount in items],
    )
