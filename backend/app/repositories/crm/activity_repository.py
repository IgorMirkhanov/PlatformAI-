"""CRM activity repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.activity import ActivityType, CrmActivity
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class ActivityRepository(BaseCrmRepository[CrmActivity]):
    model = CrmActivity

    async def list_filtered(
        self,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        activity_type: ActivityType | None = None,
        only_open: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrmActivity]:
        stmt = self._base_query().order_by(CrmActivity.due_at.asc().nullslast(), CrmActivity.created_at.desc())
        if deal_id is not None:
            stmt = stmt.where(CrmActivity.deal_id == deal_id)
        if contact_id is not None:
            stmt = stmt.where(CrmActivity.contact_id == contact_id)
        if activity_type is not None:
            stmt = stmt.where(CrmActivity.type == activity_type)
        if only_open:
            stmt = stmt.where(CrmActivity.completed_at.is_(None))
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_filtered(
        self,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        activity_type: ActivityType | None = None,
        only_open: bool = False,
    ) -> int:
        stmt = select(func.count()).select_from(CrmActivity).where(
            CrmActivity.organization_id == self.organization_id
        )
        if deal_id is not None:
            stmt = stmt.where(CrmActivity.deal_id == deal_id)
        if contact_id is not None:
            stmt = stmt.where(CrmActivity.contact_id == contact_id)
        if activity_type is not None:
            stmt = stmt.where(CrmActivity.type == activity_type)
        if only_open:
            stmt = stmt.where(CrmActivity.completed_at.is_(None))
        value = await self.session.scalar(stmt)
        return int(value or 0)


def activity_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> ActivityRepository:
    return ActivityRepository(session, organization_id=organization_id)
