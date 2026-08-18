"""CRM API key service — generate, hash, verify (raw secret never stored)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm.api_key import CrmApiKey
from app.repositories.crm.api_key_repository import (
    api_key_repository,
    get_active_api_key_by_hash,
)
from app.schemas.crm.api_keys import (
    CrmApiKeyCreate,
    CrmApiKeyCreated,
    CrmApiKeyListResponse,
    CrmApiKeyRead,
)
from app.services.security_audit_service import security_audit_service

API_KEY_PREFIX = "mpai_crm_"
API_KEY_SECRET_BYTES = 24  # ~32 url-safe chars


def generate_raw_api_key() -> str:
    """Return ``mpai_crm_`` + cryptographically strong random secret."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(API_KEY_SECRET_BYTES)}"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def api_key_display_prefix(raw_key: str) -> str:
    """First 16 chars for UI (e.g. ``mpai_crm_a1b2c3d``)."""
    return raw_key[:16]


@dataclass(frozen=True, slots=True)
class VerifiedCrmApiKey:
    organization_id: uuid.UUID
    api_key: CrmApiKey


class ApiKeyServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ApiKeyService:
    def _repo(self, db: AsyncSession, organization_id: uuid.UUID):
        return api_key_repository(db, organization_id=organization_id)

    async def list_keys(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> CrmApiKeyListResponse:
        repo = self._repo(db, organization_id)
        items = await repo.list_ordered(limit=limit, offset=offset)
        total = await repo.count_all()
        return CrmApiKeyListResponse(
            items=[CrmApiKeyRead.model_validate(row) for row in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def create_api_key(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        payload: CrmApiKeyCreate,
        *,
        created_by_id: uuid.UUID | None = None,
    ) -> CrmApiKeyCreated:
        raw = generate_raw_api_key()
        entity = CrmApiKey(
            organization_id=organization_id,
            label=payload.label,
            key_hash=hash_api_key(raw),
            key_prefix=api_key_display_prefix(raw),
            is_active=True,
            created_by_id=created_by_id,
        )
        await self._repo(db, organization_id).add(entity)
        logger.info(
            "CRM.api_key_created | org={org} key_id={key_id} prefix={prefix}",
            org=organization_id,
            key_id=entity.id,
            prefix=entity.key_prefix,
        )
        base = CrmApiKeyRead.model_validate(entity)
        return CrmApiKeyCreated(**base.model_dump(), api_key=raw)

    async def delete_api_key(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        key_id: uuid.UUID,
        *,
        hard_delete: bool = True,
        actor_user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> None:
        repo = self._repo(db, organization_id)
        entity = await repo.get(key_id)
        if entity is None:
            raise ApiKeyServiceError("API key not found.", status_code=404)
        label = entity.label
        if hard_delete:
            await repo.delete(entity)
        else:
            entity.is_active = False
            await db.flush()
        await security_audit_service.api_key_revoked(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            key_id=key_id,
            label=label,
            hard_delete=hard_delete,
            ip_address=ip_address,
        )
        logger.info(
            "CRM.api_key_revoked | org={org} key_id={key_id} hard={hard}",
            org=organization_id,
            key_id=key_id,
            hard=hard_delete,
        )

    async def verify_raw_key(
        self,
        db: AsyncSession,
        raw_key: str,
    ) -> VerifiedCrmApiKey | None:
        cleaned = (raw_key or "").strip()
        if not cleaned:
            return None
        digest = hash_api_key(cleaned)
        row = await get_active_api_key_by_hash(db, digest)
        if row is None:
            return None
        await api_key_repository(db, organization_id=row.organization_id).touch_last_used(row)
        return VerifiedCrmApiKey(organization_id=row.organization_id, api_key=row)


api_key_service = ApiKeyService()
