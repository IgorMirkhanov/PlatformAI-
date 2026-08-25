"""Credentials vault repository — decrypt only for orchestrator/CRM workers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_credentials import CredentialStatus, TenantCredential
from app.services.crypto_service import current_key_version, decrypt_payload, encrypt_payload


class CredentialsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        organization_id: uuid.UUID,
        kind: str,
        payload: dict[str, Any],
        label: str | None = None,
        oauth_expires_at: datetime | None = None,
        status: str = CredentialStatus.ACTIVE.value,
    ) -> TenantCredential:
        stmt = select(TenantCredential).where(
            TenantCredential.organization_id == organization_id,
            TenantCredential.kind == kind,
            TenantCredential.label.is_(label) if label is None else TenantCredential.label == label,
        )
        row = await self.session.scalar(stmt)
        ciphertext, iv, tag = encrypt_payload(payload)
        version = current_key_version()
        if row is None:
            row = TenantCredential(
                organization_id=organization_id,
                kind=kind,
                label=label,
                encrypted_payload=ciphertext,
                encryption_iv=iv,
                encryption_tag=tag,
                key_version=version,
                oauth_expires_at=oauth_expires_at,
                status=status,
            )
            self.session.add(row)
        else:
            row.encrypted_payload = ciphertext
            row.encryption_iv = iv
            row.encryption_tag = tag
            row.key_version = version
            row.oauth_expires_at = oauth_expires_at
            row.status = status
            row.last_error = None
            row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return row

    async def get_decrypted(
        self,
        organization_id: uuid.UUID,
        kind: str,
        label: str | None = None,
    ) -> dict[str, Any] | None:
        stmt = select(TenantCredential).where(
            TenantCredential.organization_id == organization_id,
            TenantCredential.kind == kind,
            TenantCredential.status == CredentialStatus.ACTIVE.value,
        )
        if label is None:
            stmt = stmt.where(TenantCredential.label.is_(None))
        else:
            stmt = stmt.where(TenantCredential.label == label)
        row = await self.session.scalar(stmt)
        if row is None and label is None:
            stmt = (
                select(TenantCredential)
                .where(
                    TenantCredential.organization_id == organization_id,
                    TenantCredential.kind == kind,
                    TenantCredential.status == CredentialStatus.ACTIVE.value,
                )
                .order_by(TenantCredential.updated_at.desc())
                .limit(1)
            )
            row = await self.session.scalar(stmt)
        if row is None:
            return None
        return decrypt_payload(
            row.encrypted_payload,
            row.encryption_iv,
            row.encryption_tag,
            key_version=int(row.key_version),
        )

    async def mark_error(self, credential_id: uuid.UUID, error: str) -> None:
        row = await self.session.get(TenantCredential, credential_id)
        if row is None:
            return
        row.status = CredentialStatus.ERROR.value
        row.last_error = error[:2000]
        row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def revoke(self, credential_id: uuid.UUID) -> None:
        """Clear sealed payload and mark vault row revoked (disconnect / ONAPPUNINSTALL)."""
        row = await self.session.get(TenantCredential, credential_id)
        if row is None:
            return
        row.status = CredentialStatus.REVOKED.value
        ciphertext, iv, tag = encrypt_payload({})
        row.encrypted_payload = ciphertext
        row.encryption_iv = iv
        row.encryption_tag = tag
        row.key_version = current_key_version()
        row.oauth_expires_at = None
        row.last_error = None
        row.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def list_for_org(self, organization_id: uuid.UUID) -> list[TenantCredential]:
        stmt = (
            select(TenantCredential)
            .where(TenantCredential.organization_id == organization_id)
            .order_by(TenantCredential.updated_at.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def get(self, credential_id: uuid.UUID) -> TenantCredential | None:
        return await self.session.get(TenantCredential, credential_id)
