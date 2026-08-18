"""CRM note repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.note import CrmNote
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class NoteRepository(BaseCrmRepository[CrmNote]):
    model = CrmNote

    async def list_filtered(
        self,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrmNote]:
        stmt = self._base_query().order_by(CrmNote.created_at.desc())
        if deal_id is not None:
            stmt = stmt.where(CrmNote.deal_id == deal_id)
        if contact_id is not None:
            stmt = stmt.where(CrmNote.contact_id == contact_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_filtered(
        self,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(CrmNote).where(
            CrmNote.organization_id == self.organization_id
        )
        if deal_id is not None:
            stmt = stmt.where(CrmNote.deal_id == deal_id)
        if contact_id is not None:
            stmt = stmt.where(CrmNote.contact_id == contact_id)
        value = await self.session.scalar(stmt)
        return int(value or 0)


def note_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> NoteRepository:
    return NoteRepository(session, organization_id=organization_id)
