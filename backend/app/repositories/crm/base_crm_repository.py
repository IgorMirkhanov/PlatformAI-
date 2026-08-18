"""Tenant-scoped CRM repository base — every query filters by organization_id."""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class BaseCrmRepository(Generic[ModelT]):
    """
    Mandatory tenant gate for native CRM tables.

    ``organization_id`` is required. There is no public ``get_by_id`` that
    skips the tenant filter — use ``get(entity_id)`` which always scopes.
    """

    model: type[ModelT]
    tenant_field: str = "organization_id"

    def __init__(self, session: AsyncSession, *, organization_id: uuid.UUID) -> None:
        if organization_id is None:  # type: ignore[comparison-overlap]
            raise ValueError("organization_id is required for CRM repositories.")
        self.session = session
        self.organization_id = organization_id

    def _base_query(self) -> Select[Any]:
        return select(self.model).where(
            getattr(self.model, self.tenant_field) == self.organization_id
        )

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        stmt = self._base_query().where(self.model.id == entity_id)  # type: ignore[attr-defined]
        return await self.session.scalar(stmt)

    async def list(self, *, limit: int = 200, offset: int = 0) -> list[ModelT]:
        stmt = self._base_query().limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def add(self, entity: ModelT) -> ModelT:
        setattr(entity, self.tenant_field, self.organization_id)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def reorder(self, positions: list[tuple[uuid.UUID, int]]) -> int:
        """
        Apply ``(id, position)`` pairs for entities in this tenant.

        Returns the number of rows updated.
        """
        if not positions:
            return 0
        updated = 0
        for entity_id, position in positions:
            result = await self.session.execute(
                update(self.model)
                .where(
                    self.model.id == entity_id,  # type: ignore[attr-defined]
                    getattr(self.model, self.tenant_field) == self.organization_id,
                )
                .values(position=int(position))
            )
            updated += int(result.rowcount or 0)
        await self.session.flush()
        return updated
