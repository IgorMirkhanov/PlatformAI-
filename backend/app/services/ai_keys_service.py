"""Organization LLM API key vault — Fernet encryption + gateway resolution."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Final

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import resolve_encryption_key_material, resolve_retired_key_materials
from app.models.organization_api_key import OrganizationApiKey
from app.schemas.organization_api_keys import (
    OrganizationApiKeyListResponse,
    OrganizationApiKeyProviderStatus,
    OrganizationApiKeyUpsertResponse,
)

FERNET_PREFIX: Final[str] = "fernet:"

SUPPORTED_LLM_KEY_PROVIDERS: Final[tuple[str, ...]] = (
    "openai",
    "anthropic",
    "deepseek",
    "gemini",
    "glm",
    "qwen",
)

_PROVIDER_LABELS: Final[dict[str, str]] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "gemini": "Google Gemini",
    "glm": "GLM (Zhipu)",
    "qwen": "Qwen (DashScope)",
}


class AiKeysServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _normalize_provider(provider: str) -> str:
    key = (provider or "").strip().lower()
    if key not in SUPPORTED_LLM_KEY_PROVIDERS:
        raise AiKeysServiceError(
            f"Unsupported provider '{provider}'. "
            f"Allowed: {', '.join(SUPPORTED_LLM_KEY_PROVIDERS)}.",
            400,
        )
    return key


def _fernet_key_material() -> bytes:
    # Same precedence as app.core.crypto so one key governs every at-rest store.
    raw = resolve_encryption_key_material()
    if not raw or not str(raw).strip():
        raise AiKeysServiceError(
            "CREDENTIALS_ENCRYPTION_KEY / ENCRYPTION_KEY is not configured on the server.",
            500,
        )
    return str(raw).strip().encode("utf-8")


def _fernet_for(material: bytes):
    from cryptography.fernet import Fernet

    try:
        return Fernet(material)
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(material).digest())
        return Fernet(derived)


def _fernet_instance():
    """Fernet bound to the active key — used for writes."""
    return _fernet_for(_fernet_key_material())


def _fernet_read_instances() -> list[Any]:
    """Active key first, then retired rotation keys, for decryption only."""
    instances = [_fernet_instance()]
    for material in resolve_retired_key_materials():
        instances.append(_fernet_for(material.strip().encode("utf-8")))
    return instances


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt API key with Fernet for database storage."""
    token = _fernet_instance().encrypt(plaintext.strip().encode("utf-8")).decode("ascii")
    return f"{FERNET_PREFIX}{token}"


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt Fernet payload from ``encrypted_api_key`` column."""
    value = (ciphertext or "").strip()
    if not value:
        raise AiKeysServiceError("Encrypted API key payload is empty.", 500)
    if not value.startswith(FERNET_PREFIX):
        raise AiKeysServiceError("Unsupported API key encryption format.", 500)
    token = value.removeprefix(FERNET_PREFIX).encode("ascii")

    for index, fernet in enumerate(_fernet_read_instances()):
        try:
            plaintext = fernet.decrypt(token).decode("utf-8")
        except Exception:
            continue
        if index > 0:
            logger.warning(
                "AiKeys.decrypted_with_retired_key | retired_key_index={index} "
                "hint=run scripts/reencrypt_credentials.py to migrate onto the active key",
                index=index,
            )
        return plaintext

    raise AiKeysServiceError(
        "Stored API key cannot be decrypted with the configured encryption key. "
        "Re-enter the key, or add the previous key to CREDENTIALS_ENCRYPTION_KEYS_OLD.",
        500,
    )


def mask_api_key(plaintext: str) -> str:
    """Mask secret for API responses, e.g. ``sk-...abcd``."""
    secret = (plaintext or "").strip()
    if not secret:
        return "***"
    if len(secret) <= 8:
        return f"{secret[:2]}...{secret[-2:]}"
    prefix = secret.split("-", 1)[0] if "-" in secret[:12] else secret[:3]
    return f"{prefix}-...{secret[-4:]}"


class AiKeysService:
    async def list_provider_status(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> OrganizationApiKeyListResponse:
        result = await db.execute(
            select(OrganizationApiKey).where(
                OrganizationApiKey.organization_id == organization_id
            )
        )
        rows = {row.provider: row for row in result.scalars().all()}

        items: list[OrganizationApiKeyProviderStatus] = []
        for provider in SUPPORTED_LLM_KEY_PROVIDERS:
            row = rows.get(provider)
            if row is None:
                items.append(
                    OrganizationApiKeyProviderStatus(
                        provider=provider,
                        label=_PROVIDER_LABELS.get(provider, provider),
                        configured=False,
                        is_active=False,
                        masked_key=None,
                        updated_at=None,
                    )
                )
                continue
            masked: str | None = None
            if row.encrypted_api_key:
                try:
                    masked = mask_api_key(decrypt_api_key(row.encrypted_api_key))
                except Exception:
                    masked = "configured"
            items.append(
                OrganizationApiKeyProviderStatus(
                    provider=provider,
                    label=_PROVIDER_LABELS.get(provider, provider),
                    configured=True,
                    is_active=bool(row.is_active),
                    masked_key=masked,
                    updated_at=row.updated_at,
                )
            )
        return OrganizationApiKeyListResponse(items=items)

    async def upsert_key(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        provider: str,
        api_key: str,
        is_active: bool = True,
    ) -> OrganizationApiKeyUpsertResponse:
        provider_id = _normalize_provider(provider)
        secret = api_key.strip()
        if len(secret) < 8:
            raise AiKeysServiceError("API key is too short.", 400)

        encrypted = encrypt_api_key(secret)
        result = await db.execute(
            select(OrganizationApiKey).where(
                OrganizationApiKey.organization_id == organization_id,
                OrganizationApiKey.provider == provider_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = OrganizationApiKey(
                organization_id=organization_id,
                provider=provider_id,
                encrypted_api_key=encrypted,
                is_active=is_active,
            )
            db.add(row)
        else:
            row.encrypted_api_key = encrypted
            row.is_active = is_active
            row.updated_at = datetime.now(timezone.utc)

        await db.flush()
        try:
            from app.models.tenant_credentials import PROVIDER_TO_LLM_KIND
            from app.repositories.credentials_repository import CredentialsRepository

            kind = PROVIDER_TO_LLM_KIND.get(provider_id)
            if kind:
                await CredentialsRepository(db).upsert(
                    organization_id=organization_id,
                    kind=kind,
                    payload={"api_key": secret, "provider": provider_id},
                    status="active" if is_active else "revoked",
                )
        except Exception as exc:
            logger.warning(
                "AiKeys.vault_sync_failed | org={org} provider={provider} error={error}",
                org=organization_id,
                provider=provider_id,
                error=str(exc),
            )
        logger.info(
            "AiKeys.upsert | org={org} provider={provider} active={active}",
            org=organization_id,
            provider=provider_id,
            active=is_active,
        )
        return OrganizationApiKeyUpsertResponse(
            provider=provider_id,
            configured=True,
            masked_key=mask_api_key(secret),
            is_active=is_active,
        )

    async def delete_key(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        provider: str,
    ) -> None:
        provider_id = _normalize_provider(provider)
        result = await db.execute(
            select(OrganizationApiKey).where(
                OrganizationApiKey.organization_id == organization_id,
                OrganizationApiKey.provider == provider_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise AiKeysServiceError("API key not found for this provider.", 404)
        await db.delete(row)
        await db.flush()
        logger.info(
            "AiKeys.delete | org={org} provider={provider}",
            org=organization_id,
            provider=provider_id,
        )

    async def get_active_keys_map(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> dict[str, str]:
        """Return decrypted active keys keyed by provider id."""
        result = await db.execute(
            select(OrganizationApiKey).where(
                OrganizationApiKey.organization_id == organization_id,
                OrganizationApiKey.is_active.is_(True),
            )
        )
        out: dict[str, str] = {}
        for row in result.scalars().all():
            try:
                out[row.provider] = decrypt_api_key(row.encrypted_api_key)
            except Exception as exc:
                logger.warning(
                    "AiKeys.decrypt_failed | org={org} provider={provider} error={error}",
                    org=organization_id,
                    provider=row.provider,
                    error=str(exc),
                )
        try:
            from app.models.tenant_credentials import LLM_KIND_TO_PROVIDER, TenantCredential
            from app.services.crypto_service import decrypt_payload

            vault = await db.execute(
                select(TenantCredential).where(
                    TenantCredential.organization_id == organization_id,
                    TenantCredential.status == "active",
                    TenantCredential.kind.in_(tuple(LLM_KIND_TO_PROVIDER.keys())),
                )
            )
            for cred in vault.scalars().all():
                provider = LLM_KIND_TO_PROVIDER.get(cred.kind)
                if not provider or provider in out:
                    continue
                payload = decrypt_payload(
                    cred.encrypted_payload,
                    cred.encryption_iv,
                    cred.encryption_tag,
                    key_version=int(cred.key_version),
                )
                secret = str(payload.get("api_key") or payload.get("token") or "")
                if secret:
                    out[provider] = secret
        except Exception as exc:
            logger.debug("AiKeys.vault_read_skip | error={error}", error=str(exc))
        return out

    async def resolve_provider_api_key(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        provider_id: str,
    ) -> str | None:
        provider = _normalize_provider(provider_id)
        result = await db.execute(
            select(OrganizationApiKey).where(
                OrganizationApiKey.organization_id == organization_id,
                OrganizationApiKey.provider == provider,
                OrganizationApiKey.is_active.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return decrypt_api_key(row.encrypted_api_key)


ai_keys_service = AiKeysService()
