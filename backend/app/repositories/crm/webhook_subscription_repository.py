"""CRM webhook subscription repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.webhook_subscription import CrmWebhookSubscription
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class WebhookSubscriptionRepository(BaseCrmRepository[CrmWebhookSubscription]):
    model = CrmWebhookSubscription

    async def list_ordered(self, *, limit: int = 100, offset: int = 0) -> list[CrmWebhookSubscription]:
        stmt = (
            self._base_query()
            .order_by(CrmWebhookSubscription.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(CrmWebhookSubscription).where(
            CrmWebhookSubscription.organization_id == self.organization_id
        )
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def list_active_for_event(self, event_type: str) -> list[CrmWebhookSubscription]:
        """
        Active subscriptions that listen for ``event_type`` or the wildcard ``*``.
        """
        stmt = self._base_query().where(
            CrmWebhookSubscription.is_active.is_(True),
            or_(
                CrmWebhookSubscription.event_types.contains([event_type]),
                CrmWebhookSubscription.event_types.contains(["*"]),
            ),
        )
        result = await self.session.scalars(stmt)
        return list(result.all())


def webhook_subscription_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> WebhookSubscriptionRepository:
    return WebhookSubscriptionRepository(session, organization_id=organization_id)
