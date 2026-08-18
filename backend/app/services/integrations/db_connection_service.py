"""CRUD service for organization encrypted SQL DB connections."""

from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_sensitive, encrypt_sensitive
from app.models.integrations.db_connection import OrganizationDbConnection
from app.schemas.integrations.db_connections import (
    DbConnectionCreate,
    DbConnectionListResponse,
    DbConnectionOut,
)


class DbConnectionServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


_ALLOWED_DB_TYPES = frozenset({"postgresql", "mysql"})


class DbConnectionService:
    async def list_connections(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> DbConnectionListResponse:
        stmt = (
            select(OrganizationDbConnection)
            .where(OrganizationDbConnection.organization_id == organization_id)
            .order_by(OrganizationDbConnection.created_at.desc())
        )
        rows = list((await db.execute(stmt)).scalars().all())
        return DbConnectionListResponse(
            items=[DbConnectionOut.model_validate(row) for row in rows],
            total=len(rows),
        )

    async def create_connection(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: DbConnectionCreate,
        *,
        created_by_id: uuid.UUID | None = None,
    ) -> DbConnectionOut:
        db_type = payload.db_type.strip().lower()
        if db_type not in _ALLOWED_DB_TYPES:
            raise DbConnectionServiceError(
                "db_type must be postgresql or mysql.",
                status_code=400,
            )

        connection_string = payload.connection_string.strip()
        if not connection_string:
            raise DbConnectionServiceError("connection_string is required.", status_code=400)

        entity = OrganizationDbConnection(
            organization_id=organization_id,
            name=payload.name.strip(),
            db_type=db_type,
            connection_string_encrypted=encrypt_sensitive(connection_string),
            created_by_id=created_by_id,
        )
        db.add(entity)
        await db.commit()
        await db.refresh(entity)

        logger.info(
            "Integrations.db_connection_created | org={org} id={id} db_type={db_type}",
            org=organization_id,
            id=entity.id,
            db_type=db_type,
        )
        return DbConnectionOut.model_validate(entity)

    async def delete_connection(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> None:
        entity = await self.get_entity(db, organization_id, connection_id)
        await db.delete(entity)
        await db.commit()
        logger.info(
            "Integrations.db_connection_deleted | org={org} id={id}",
            org=organization_id,
            id=connection_id,
        )

    async def get_entity(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> OrganizationDbConnection:
        stmt = select(OrganizationDbConnection).where(
            OrganizationDbConnection.id == connection_id,
            OrganizationDbConnection.organization_id == organization_id,
        )
        entity = (await db.execute(stmt)).scalar_one_or_none()
        if entity is None:
            raise DbConnectionServiceError("Database connection not found.", status_code=404)
        return entity

    async def resolve_connection_string(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> str:
        """Decrypt a stored connection string for runtime Flow execution."""
        entity = await self.get_entity(db, organization_id, connection_id)
        value = decrypt_sensitive(entity.connection_string_encrypted).strip()
        if not value:
            raise DbConnectionServiceError(
                "Stored connection string is empty or corrupt.",
                status_code=500,
            )
        return value


db_connection_service = DbConnectionService()
