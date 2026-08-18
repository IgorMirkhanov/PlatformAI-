"""Admin dashboard / platform stats."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.admin import get_current_admin
from app.core.database import get_db
from app.models.core_models import BillingTransaction, BillingTransactionStatus, Bot, BotDiagnosticLog, Company
from app.models.usage import LLMUsageLog
from app.models.users import User
from app.schemas.admin import AdminStatsResponse

router = APIRouter(tags=["admin-dashboard"])


@router.get(
    "/stats",
    response_model=AdminStatsResponse,
    summary="Global platform metrics for Admin analytics cards",
)
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> AdminStatsResponse:
    _ = current_user
    total_orgs = await db.scalar(
        select(func.count()).select_from(Company).where(Company.deleted_at.is_(None))
    )
    total_bots = await db.scalar(
        select(func.count())
        .select_from(Bot)
        .where(Bot.is_active.is_(True), Bot.deleted_at.is_(None))
    )
    revenue = await db.scalar(
        select(func.coalesce(func.sum(BillingTransaction.amount), 0)).where(
            BillingTransaction.status.in_(
                [BillingTransactionStatus.SUCCESS, BillingTransactionStatus.APPROVED]
            )
        )
    )
    llm_cost = await db.scalar(
        select(func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0))
    )
    total_tokens = await db.scalar(
        select(
            func.coalesce(
                func.sum(LLMUsageLog.prompt_tokens + LLMUsageLog.completion_tokens),
                0,
            )
        )
    )
    error_log_count = await db.scalar(
        select(func.count()).select_from(BotDiagnosticLog)
    )
    return AdminStatsResponse(
        total_organizations=int(total_orgs or 0),
        total_active_bots=int(total_bots or 0),
        total_revenue=float(revenue or 0),
        total_llm_cost=float(llm_cost or 0),
        total_tokens=int(total_tokens or 0),
        error_log_count=int(error_log_count or 0),
        currency="KZT",
    )
