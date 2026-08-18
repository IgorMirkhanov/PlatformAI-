"""CRM custom field definition repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.custom_field import CrmCustomFieldDefinition, CrmEntityType
from app.repositories.crm.base_crm_repository import BaseCrmRepository


class CustomFieldRepository(BaseCrmRepository[CrmCustomFieldDefinition]):
    model = CrmCustomFieldDefinition

    async def list_filtered(
        self,
        *,
        entity_type: CrmEntityType | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[CrmCustomFieldDefinition]:
        stmt = self._base_query().order_by(
            CrmCustomFieldDefinition.entity_type.asc(),
            CrmCustomFieldDefinition.position.asc(),
            CrmCustomFieldDefinition.created_at.asc(),
        )
        if entity_type is not None:
            stmt = stmt.where(CrmCustomFieldDefinition.entity_type == entity_type)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_filtered(self, *, entity_type: CrmEntityType | None = None) -> int:
        stmt = select(func.count()).select_from(CrmCustomFieldDefinition).where(
            CrmCustomFieldDefinition.organization_id == self.organization_id
        )
        if entity_type is not None:
            stmt = stmt.where(CrmCustomFieldDefinition.entity_type == entity_type)
        value = await self.session.scalar(stmt)
        return int(value or 0)

    async def get_by_key(
        self,
        *,
        entity_type: CrmEntityType,
        field_key: str,
    ) -> CrmCustomFieldDefinition | None:
        stmt = self._base_query().where(
            CrmCustomFieldDefinition.entity_type == entity_type,
            CrmCustomFieldDefinition.field_key == field_key,
        )
        return await self.session.scalar(stmt)


def custom_field_repository(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> CustomFieldRepository:
    return CustomFieldRepository(session, organization_id=organization_id)
