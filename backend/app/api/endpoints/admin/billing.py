"""Admin billing ledger + diagnostic system logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_superadmin
from app.api.endpoints.admin.common import diagnostic_level, public_tx_status
from app.core.database import get_db
from app.models.core_models import BillingTransaction, BotDiagnosticLog, Company
from app.models.users import User
from app.schemas.admin import (
    AdminLogItem,
    AdminLogListResponse,
    AdminTransactionItem,
    AdminTransactionListResponse,
)

router = APIRouter(tags=["admin-billing"])


@router.get(
    "/transactions",
    response_model=AdminTransactionListResponse,
    summary="Global billing transaction ledger for Admin CRM",
)
async def list_admin_transactions(
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> AdminTransactionListResponse:
    _ = current_user
    Payer = aliased(User)
    stmt = (
        select(
            BillingTransaction,
            Payer.email.label("user_email"),
            Company.name.label("organization_name"),
        )
        .outerjoin(Payer, Payer.id == BillingTransaction.user_id)
        .outerjoin(Company, Company.id == BillingTransaction.organization_id)
        .order_by(BillingTransaction.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()
    transactions = [
        AdminTransactionItem(
            id=txn.id,
            organization_id=txn.organization_id,
            organization_name=org_name,
            user_id=txn.user_id,
            user_email=str(email or ""),
            amount=float(txn.amount),
            currency=txn.currency or "KZT",
            status=public_tx_status(txn.status),
            status_raw=txn.status.value if hasattr(txn.status, "value") else str(txn.status),
            transaction_type=(
                txn.transaction_type.value
                if hasattr(txn.transaction_type, "value")
                else str(txn.transaction_type)
            ),
            description=txn.description or "",
            created_at=txn.created_at,
        )
        for txn, email, org_name in rows
    ]
    return AdminTransactionListResponse(transactions=transactions, total=len(transactions))


@router.get(
    "/logs",
    response_model=AdminLogListResponse,
    summary="Latest system diagnostic logs for Admin Panel",
)
async def list_admin_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> AdminLogListResponse:
    _ = current_user
    result = await db.execute(
        select(BotDiagnosticLog).order_by(BotDiagnosticLog.created_at.desc()).limit(limit)
    )
    rows = list(result.scalars().all())
    logs = [
        AdminLogItem(
            id=row.id,
            level=diagnostic_level(row.error_type),
            action=(
                row.error_type.value if hasattr(row.error_type, "value") else str(row.error_type)
            ),
            message=row.error_message or "",
            created_at=row.created_at,
            bot_id=row.bot_id,
        )
        for row in rows
    ]
    return AdminLogListResponse(logs=logs, total=len(logs))
