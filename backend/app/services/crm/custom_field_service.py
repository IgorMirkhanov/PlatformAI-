"""CRM custom field definition service — schema CRUD only."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.custom_field import CrmCustomFieldDefinition, CrmEntityType, CrmFieldType
from app.repositories.crm.custom_field_repository import custom_field_repository
from app.schemas.crm.tags_fields import (
    CrmCustomFieldCreate,
    CrmCustomFieldListResponse,
    CrmCustomFieldRead,
    CrmCustomFieldUpdate,
)


class CustomFieldServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class CustomFieldService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return custom_field_repository(db, organization_id=organization_id)

    async def list_definitions(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        entity_type: CrmEntityType | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> CrmCustomFieldListResponse:
        repo = self._repo(db, organization_id)
        items = await repo.list_filtered(entity_type=entity_type, limit=limit, offset=offset)
        total = await repo.count_filtered(entity_type=entity_type)
        return CrmCustomFieldListResponse(
            items=[CrmCustomFieldRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_definition(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        field_id: uuid.UUID,
    ) -> CrmCustomFieldRead:
        row = await self._repo(db, organization_id).get(field_id)
        if row is None:
            raise CustomFieldServiceError("Custom field definition not found.", status_code=404)
        return CrmCustomFieldRead.model_validate(row)

    async def create_definition(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmCustomFieldCreate,
    ) -> CrmCustomFieldRead:
        repo = self._repo(db, organization_id)
        existing = await repo.get_by_key(
            entity_type=payload.entity_type,
            field_key=payload.field_key,
        )
        if existing is not None:
            raise CustomFieldServiceError(
                "A field with this field_key already exists for this entity_type.",
                status_code=409,
            )
        entity = CrmCustomFieldDefinition(
            organization_id=organization_id,
            entity_type=payload.entity_type,
            field_key=payload.field_key,
            label=payload.label,
            field_type=payload.field_type,
            options=payload.options,
            is_required=payload.is_required,
            position=payload.position,
        )
        try:
            await repo.add(entity)
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise CustomFieldServiceError(
                "A field with this field_key already exists for this entity_type.",
                status_code=409,
            ) from exc
        return CrmCustomFieldRead.model_validate(entity)

    async def update_definition(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        field_id: uuid.UUID,
        payload: CrmCustomFieldUpdate,
    ) -> CrmCustomFieldRead:
        repo = self._repo(db, organization_id)
        entity = await repo.get(field_id)
        if entity is None:
            raise CustomFieldServiceError("Custom field definition not found.", status_code=404)

        data = payload.model_dump(exclude_unset=True)
        next_type = data.get("field_type", entity.field_type)
        next_options = data.get("options", entity.options)
        if next_type in {CrmFieldType.SELECT, CrmFieldType.MULTISELECT} and not next_options:
            raise CustomFieldServiceError(
                "options are required for select/multiselect fields.",
                status_code=400,
            )

        for key, value in data.items():
            setattr(entity, key, value)
        await db.flush()
        return CrmCustomFieldRead.model_validate(entity)

    async def delete_definition(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        field_id: uuid.UUID,
    ) -> None:
        repo = self._repo(db, organization_id)
        entity = await repo.get(field_id)
        if entity is None:
            raise CustomFieldServiceError("Custom field definition not found.", status_code=404)
        await repo.delete(entity)


custom_field_service = CustomFieldService()
