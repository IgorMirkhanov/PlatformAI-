"""CRM contact repository."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.contact import CrmContact
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class ContactRepository(BaseCrmRepository[CrmContact]):
    model = CrmContact

    async def get_by_linked_client_id(self, client_id: uuid.UUID) -> CrmContact | None:
        stmt = self._base_query().where(CrmContact.linked_client_id == client_id)
        return await self.session.scalar(stmt)

    async def find_by_phone_or_email(
        self,
        *,
        phone: str | None = None,
        email: str | None = None,
    ) -> CrmContact | None:
        """Match an existing contact by exact phone and/or email (tenant-scoped)."""
        phone_n = (phone or "").strip() or None
        email_n = (email or "").strip() or None
        if not phone_n and not email_n:
            return None
        clauses = []
        if phone_n:
            clauses.append(CrmContact.phone == phone_n)
        if email_n:
            clauses.append(CrmContact.email.ilike(email_n))
        stmt = (
            self._base_query()
            .where(or_(*clauses))
            .order_by(CrmContact.updated_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def list_filtered(
        self,
        *,
        q: str | None = None,
        account_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrmContact]:
        stmt = self._base_query().order_by(CrmContact.created_at.desc())
        if account_id is not None:
            stmt = stmt.where(CrmContact.account_id == account_id)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    CrmContact.first_name.ilike(pattern),
                    CrmContact.last_name.ilike(pattern),
                    CrmContact.email.ilike(pattern),
                    CrmContact.phone.ilike(pattern),
                )
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_filtered(
        self,
        *,
        q: str | None = None,
        account_id: uuid.UUID | None = None,
    ) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(CrmContact).where(
            CrmContact.organization_id == self.organization_id
        )
        if account_id is not None:
            stmt = stmt.where(CrmContact.account_id == account_id)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    CrmContact.first_name.ilike(pattern),
                    CrmContact.last_name.ilike(pattern),
                    CrmContact.email.ilike(pattern),
                    CrmContact.phone.ilike(pattern),
                )
            )
        value = await self.session.scalar(stmt)
        return int(value or 0)


def contact_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> ContactRepository:
    return ContactRepository(session, organization_id=organization_id)
