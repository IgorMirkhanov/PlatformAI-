"""Helpers for writing tenant security audit events."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security.audit_log import AuditLog


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return None


class SecurityAuditService:
    async def write(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        action: str,
        user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            ip_address=ip_address,
            details=details,
        )
        db.add(entry)
        await db.flush()
        return entry

    async def list_for_organization(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
        action: str | None = None,
    ) -> list[AuditLog]:
        """Return audit rows scoped strictly to ``organization_id``."""
        stmt = select(AuditLog).where(AuditLog.organization_id == organization_id)
        if action:
            stmt = stmt.where(AuditLog.action == action.strip().upper())
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
        return list((await db.execute(stmt)).scalars().all())

    async def api_key_revoked(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        key_id: uuid.UUID,
        label: str | None,
        hard_delete: bool,
        ip_address: str | None = None,
    ) -> AuditLog:
        return await self.write(
            db,
            organization_id=organization_id,
            user_id=actor_user_id,
            action="API_KEY_REVOKED",
            ip_address=ip_address,
            details={
                "key_id": str(key_id),
                "label": label,
                "hard_delete": hard_delete,
            },
        )

    async def role_changed(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        target_user_id: uuid.UUID,
        previous_role: str,
        new_role: str,
        ip_address: str | None = None,
    ) -> AuditLog:
        return await self.write(
            db,
            organization_id=organization_id,
            user_id=actor_user_id,
            action="ROLE_CHANGED",
            ip_address=ip_address,
            details={
                "target_user_id": str(target_user_id),
                "previous_role": previous_role,
                "new_role": new_role,
            },
        )

    async def invite_created(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        invitation_id: uuid.UUID,
        email: str,
        role: str,
        ip_address: str | None = None,
    ) -> AuditLog:
        return await self.write(
            db,
            organization_id=organization_id,
            user_id=actor_user_id,
            action="INVITE_CREATED",
            ip_address=ip_address,
            details={
                "invitation_id": str(invitation_id),
                "email": email,
                "role": role,
            },
        )

    client_ip = staticmethod(client_ip)


security_audit_service = SecurityAuditService()
