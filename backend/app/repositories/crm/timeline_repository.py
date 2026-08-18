"""CRM timeline event repository (append-only)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.timeline_event import CrmTimelineEvent
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class TimelineRepository(BaseCrmRepository[CrmTimelineEvent]):
    model = CrmTimelineEvent

    async def list_events(
        self,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CrmTimelineEvent]:
        stmt = self._base_query().order_by(CrmTimelineEvent.created_at.desc())
        if deal_id is not None:
            stmt = stmt.where(CrmTimelineEvent.deal_id == deal_id)
        if contact_id is not None:
            stmt = stmt.where(CrmTimelineEvent.contact_id == contact_id)
        if event_type is not None:
            stmt = stmt.where(CrmTimelineEvent.event_type == event_type)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_events(
        self,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        event_type: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(CrmTimelineEvent).where(
            CrmTimelineEvent.organization_id == self.organization_id
        )
        if deal_id is not None:
            stmt = stmt.where(CrmTimelineEvent.deal_id == deal_id)
        if contact_id is not None:
            stmt = stmt.where(CrmTimelineEvent.contact_id == contact_id)
        if event_type is not None:
            stmt = stmt.where(CrmTimelineEvent.event_type == event_type)
        value = await self.session.scalar(stmt)
        return int(value or 0)


def timeline_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> TimelineRepository:
    return TimelineRepository(session, organization_id=organization_id)
