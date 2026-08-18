"""Admin audit trail service."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_audit import AdminAuditLog


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return None


def serialize_details(details: str | dict[str, Any] | None) -> str | None:
    if details is None:
        return None
    if isinstance(details, str):
        return details[:1024]
    try:
        return json.dumps(details, default=str, separators=(",", ":"))[:1024]
    except (TypeError, ValueError):
        return str(details)[:1024]


async def write_audit(
    db: AsyncSession,
    *,
    admin_id: uuid.UUID,
    target_user_id: uuid.UUID,
    action: str,
    ip_address: str | None = None,
    organization_id: uuid.UUID | None = None,
    details: str | dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AdminAuditLog:
    meta_payload: dict[str, Any] | None = None
    if isinstance(details, dict):
        meta_payload = details
    elif metadata is not None:
        meta_payload = metadata

    entry = AdminAuditLog(
        admin_id=admin_id,
        target_user_id=target_user_id,
        organization_id=organization_id,
        action=action,
        details=serialize_details(details if not isinstance(details, dict) else None),
        metadata_json=meta_payload,
        ip_address=ip_address,
    )
    db.add(entry)
    await db.flush()
    return entry


class AuditService:
    """Thin facade used by Admin Panel endpoints."""

    write = staticmethod(write_audit)
    client_ip = staticmethod(client_ip)


audit_service = AuditService()
