"""Tenant isolation helpers for Integration Hub rows."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_hub import IntegrationAgentAction, IntegrationConnection


async def get_connection_for_workspace(
    db: AsyncSession,
    *,
    connection_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> IntegrationConnection:
    """Load a hub connection only if it belongs to the caller's workspace."""
    row = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.organization_id == organization_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Connection not found.")
    return row


async def assert_connection_workspace(
    connection: IntegrationConnection | None,
    organization_id: uuid.UUID,
) -> IntegrationConnection:
    if connection is None or connection.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Connection not found.")
    return connection


async def list_agent_actions_for_workspace(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    connection_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[IntegrationAgentAction]:
    """Audit trail — always scoped by organization_id (no cross-tenant reads)."""
    stmt = (
        select(IntegrationAgentAction)
        .where(IntegrationAgentAction.organization_id == organization_id)
        .order_by(IntegrationAgentAction.created_at.desc())
        .limit(max(1, min(int(limit), 500)))
    )
    if connection_id is not None:
        stmt = stmt.where(IntegrationAgentAction.connection_id == connection_id)
    return list((await db.scalars(stmt)).all())
