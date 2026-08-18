"""Global system notification register for admin header alerts."""

from __future__ import annotations

import uuid
from decimal import Decimal

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import (
    SystemNotification,
    SystemNotificationCategory,
    SystemNotificationSeverity,
)
from app.schemas.core_schemas import (
    SystemNotificationListResponse,
    SystemNotificationRead,
)


class NotificationService:
    """Push and list critical platform alerts (billing deposits, etc.)."""

    async def notify_pending_deposit(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
        amount: Decimal | float,
        transaction_id: uuid.UUID,
    ) -> SystemNotification:
        amount_value = Decimal(str(amount)).quantize(Decimal("0.01"))
        amount_label = f"{amount_value:,.0f}".replace(",", " ")
        message = f"Новый платеж: Ожидает проверки чека на сумму {amount_label} ₸"

        notification = SystemNotification(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            category=SystemNotificationCategory.BILLING_DEPOSIT,
            severity=SystemNotificationSeverity.CRITICAL,
            title="Проверка платежа",
            message=message,
            reference_id=str(transaction_id),
            is_read=False,
        )
        db.add(notification)
        await db.flush()
        await db.refresh(notification)

        logger.info(
            "Notification.pending_deposit | notification_id={notification_id} "
            "organization_id={organization_id} amount={amount}",
            notification_id=notification.id,
            organization_id=organization_id,
            amount=str(amount_value),
        )
        return notification

    async def notify_auto_approved_deposit(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
        amount: Decimal | float,
        transaction_id: uuid.UUID,
        kaspi_reference: str | None = None,
    ) -> SystemNotification:
        amount_value = Decimal(str(amount)).quantize(Decimal("0.01"))
        amount_label = f"{amount_value:,.0f}".replace(",", " ")
        message = f"Баланс автоматически пополнен на {amount_label} ₸ (Чек проверен)"

        notification = SystemNotification(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            category=SystemNotificationCategory.BILLING_DEPOSIT,
            severity=SystemNotificationSeverity.INFO,
            title="Автопополнение",
            message=message,
            reference_id=str(transaction_id),
            is_read=False,
        )
        db.add(notification)
        await db.flush()
        await db.refresh(notification)

        logger.info(
            "Notification.auto_approved_deposit | notification_id={notification_id} "
            "organization_id={organization_id} amount={amount} kaspi_ref={kaspi_ref}",
            notification_id=notification.id,
            organization_id=organization_id,
            amount=str(amount_value),
            kaspi_ref=kaspi_reference,
        )
        return notification

    async def list_recent(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None = None,
        limit: int = 25,
    ) -> SystemNotificationListResponse:
        stmt = select(SystemNotification).order_by(SystemNotification.created_at.desc())
        if organization_id is not None:
            stmt = stmt.where(
                (SystemNotification.organization_id == organization_id)
                | (SystemNotification.organization_id.is_(None))
            )
        stmt = stmt.limit(limit)

        result = await db.execute(stmt)
        rows = list(result.scalars().all())
        return SystemNotificationListResponse(
            notifications=[SystemNotificationRead.model_validate(row) for row in rows],
            total=len(rows),
            unread_critical=sum(
                1
                for row in rows
                if not row.is_read and row.severity == SystemNotificationSeverity.CRITICAL
            ),
        )


notification_service = NotificationService()
