"""Usage metering + wallet debit after billable actions (org-aware)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import (
    BillingTransaction,
    BillingTransactionStatus,
    BillingTransactionType,
)
from app.models.saas_metering import UsageEvent, UsageMetricType
from app.services.wallet_service import InsufficientFundsException, wallet_service


def _is_llm_metric(metric_type: UsageMetricType) -> bool:
    value = metric_type.value.upper()
    return value == "LLM_TOKENS" or "LLM" in value


class UsageService:
    async def record_and_debit(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        metric_type: UsageMetricType,
        quantity: int,
        unit_cost: Decimal | float | str = 0,
        bot_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        currency: str = "KZT",
        meta: dict[str, Any] | None = None,
        debit_wallet: bool = True,
    ) -> UsageEvent:
        qty = max(0, int(quantity))
        cost_unit = Decimal(str(unit_cost))
        total = (cost_unit * Decimal(qty)).quantize(Decimal("0.01")) if cost_unit else Decimal("0.00")

        event = UsageEvent(
            user_id=user_id,
            organization_id=organization_id,
            bot_id=bot_id,
            metric_type=metric_type,
            quantity=qty,
            unit_cost=cost_unit,
            total_cost=total,
            currency=currency,
            meta=meta or {},
        )
        db.add(event)
        await db.flush()

        if debit_wallet and total > 0:
            org_id = organization_id
            if org_id is None:
                from app.models.users import User

                user = await db.get(User, user_id)
                org_id = getattr(user, "company_id", None) if user else None

            txn_type = (
                BillingTransactionType.LLM_DEDUCTION
                if _is_llm_metric(metric_type)
                else BillingTransactionType.SUBSCRIPTION_CHARGE
            )

            if org_id is not None:
                result = await wallet_service.deduct_wallet_balance(
                    db,
                    org_id,
                    total,
                    description=f"Usage {metric_type.value} x{qty}",
                    reference_id=str(event.id),
                    bot_id=bot_id,
                    transaction_type=txn_type,
                    raise_on_insufficient=True,
                )
                logger.info(
                    "Usage.debit | org={org} user_id={user_id} metric={metric} qty={qty} "
                    "cost={cost} balance={bal}",
                    org=org_id,
                    user_id=result.user_id,
                    metric=metric_type.value,
                    qty=qty,
                    cost=str(total),
                    bal=str(result.balance_after),
                )
            else:
                sub = await wallet_service.get_locked_subscription(db, user_id)
                before = Decimal(sub.balance)
                if before < total:
                    raise InsufficientFundsException(
                        f"Insufficient funds: balance={before} KZT, required={total} KZT.",
                        balance=before,
                        required=total,
                    )
                sub.balance = before - total
                db.add(
                    BillingTransaction(
                        user_id=user_id,
                        subscription_id=sub.id,
                        organization_id=None,
                        transaction_type=txn_type,
                        status=BillingTransactionStatus.SUCCESS,
                        amount=total,
                        currency=currency,
                        description=f"Usage {metric_type.value} x{qty}",
                        reference_id=str(event.id),
                    )
                )
                await db.flush()

        from app.core.metrics import USAGE_EVENTS

        USAGE_EVENTS.labels(metric=metric_type.value).inc()

        try:
            from app.services.stripe_billing_service import stripe_billing_service

            if organization_id is not None:
                await stripe_billing_service.report_usage_for_org(
                    db,
                    organization_id=organization_id,
                    metric_type=metric_type.value,
                    quantity=qty,
                )
            else:
                await stripe_billing_service.report_usage_for_user(
                    db,
                    user_id=user_id,
                    metric_type=metric_type.value,
                    quantity=qty,
                )
        except Exception as exc:
            logger.debug("Usage.stripe_meter_skip | error={error}", error=str(exc))

        return event

    async def summarize_period(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=max(1, days))
        filters = [UsageEvent.created_at >= since]
        if organization_id is not None:
            filters.append(UsageEvent.organization_id == organization_id)
        elif user_id is not None:
            filters.append(UsageEvent.user_id == user_id)
        else:
            raise ValueError("organization_id or user_id required")

        rows = await db.execute(
            select(
                UsageEvent.metric_type,
                func.coalesce(func.sum(UsageEvent.quantity), 0),
                func.coalesce(func.sum(UsageEvent.total_cost), 0),
            )
            .where(*filters)
            .group_by(UsageEvent.metric_type)
        )
        metrics: dict[str, Any] = {}
        for metric, qty, cost in rows.all():
            metrics[metric.value] = {"quantity": int(qty or 0), "cost": float(cost or 0)}
        return {
            "period_days": days,
            "since": since.isoformat(),
            "organization_id": str(organization_id) if organization_id else None,
            "metrics": metrics,
        }


usage_service = UsageService()
