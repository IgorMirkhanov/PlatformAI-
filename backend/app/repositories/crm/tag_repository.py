"""CRM tag repository + deal↔tag M2M helpers."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.tag import CrmTag, crm_deal_tags
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class TagRepository(BaseCrmRepository[CrmTag]):
    model = CrmTag

    async def list_ordered(self, *, limit: int = 200, offset: int = 0) -> list[CrmTag]:
        stmt = self._base_query().order_by(CrmTag.name.asc()).limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(CrmTag).where(
            CrmTag.organization_id == self.organization_id
        )
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def list_for_deal(self, deal_id: uuid.UUID) -> list[CrmTag]:
        stmt = (
            self._base_query()
            .join(crm_deal_tags, crm_deal_tags.c.tag_id == CrmTag.id)
            .where(crm_deal_tags.c.deal_id == deal_id)
            .order_by(CrmTag.name.asc())
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def is_attached(self, *, deal_id: uuid.UUID, tag_id: uuid.UUID) -> bool:
        stmt = select(crm_deal_tags.c.tag_id).where(
            crm_deal_tags.c.deal_id == deal_id,
            crm_deal_tags.c.tag_id == tag_id,
        )
        return await self.session.scalar(stmt) is not None

    async def attach_to_deal(self, *, deal_id: uuid.UUID, tag_id: uuid.UUID) -> bool:
        """Attach tag to deal. Returns True if a new link was created."""
        stmt = (
            insert(crm_deal_tags)
            .values(deal_id=deal_id, tag_id=tag_id)
            .on_conflict_do_nothing()
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return bool(result.rowcount)

    async def detach_from_deal(self, *, deal_id: uuid.UUID, tag_id: uuid.UUID) -> bool:
        """Detach tag from deal. Returns True if a link was removed."""
        stmt = delete(crm_deal_tags).where(
            crm_deal_tags.c.deal_id == deal_id,
            crm_deal_tags.c.tag_id == tag_id,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return bool(result.rowcount)


def tag_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> TagRepository:
    return TagRepository(session, organization_id=organization_id)
