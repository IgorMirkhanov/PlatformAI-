"""Tenant-aware async repository base (SQLAlchemy 2.0)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class TenantRepository(Generic[ModelT]):
    """
    Data-access helper that always scopes reads to the active tenant and
    excludes soft-deleted rows when the model exposes ``deleted_at``.
    """

    model: type[ModelT]
    tenant_field: str = "organization_id"

    def __init__(
        self,
        session: AsyncSession,
        *,
        organization_id: uuid.UUID | None,
        include_deleted: bool = False,
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.include_deleted = include_deleted

    def _base_query(self) -> Select[Any]:
        stmt: Select[Any] = select(self.model)
        model = self.model
        if (
            self.organization_id is not None
            and hasattr(model, self.tenant_field)
        ):
            stmt = stmt.where(getattr(model, self.tenant_field) == self.organization_id)
        if not self.include_deleted and hasattr(model, "deleted_at"):
            stmt = stmt.where(getattr(model, "deleted_at").is_(None))
        return stmt

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        stmt = self._base_query().where(self.model.id == entity_id)  # type: ignore[attr-defined]
        return await self.session.scalar(stmt)

    async def list(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        stmt = self._base_query().limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def add(self, entity: ModelT) -> ModelT:
        if (
            self.organization_id is not None
            and hasattr(entity, self.tenant_field)
            and getattr(entity, self.tenant_field) is None
        ):
            setattr(entity, self.tenant_field, self.organization_id)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def soft_delete(self, entity: ModelT) -> ModelT:
        if hasattr(entity, "soft_delete") and callable(entity.soft_delete):
            entity.soft_delete()
        elif hasattr(entity, "deleted_at"):
            entity.deleted_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        await self.session.flush()
        return entity
