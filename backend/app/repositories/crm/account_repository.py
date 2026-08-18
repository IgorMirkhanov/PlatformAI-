"""CRM account repository."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.account import CrmAccount
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class AccountRepository(BaseCrmRepository[CrmAccount]):
    model = CrmAccount

    async def list_filtered(
        self,
        *,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrmAccount]:
        stmt = self._base_query().order_by(CrmAccount.created_at.desc())
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    CrmAccount.name.ilike(pattern),
                    CrmAccount.industry.ilike(pattern),
                    CrmAccount.website.ilike(pattern),
                )
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_filtered(self, *, q: str | None = None) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(CrmAccount).where(
            CrmAccount.organization_id == self.organization_id
        )
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    CrmAccount.name.ilike(pattern),
                    CrmAccount.industry.ilike(pattern),
                    CrmAccount.website.ilike(pattern),
                )
            )
        value = await self.session.scalar(stmt)
        return int(value or 0)


def account_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> AccountRepository:
    return AccountRepository(session, organization_id=organization_id)
