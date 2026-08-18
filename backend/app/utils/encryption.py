"""Encryption helpers re-exported for services / repositories."""

from __future__ import annotations

from typing import Any

from app.core.crypto import (
    AESGCM_PREFIX,
    decrypt_sensitive,
    decrypt_token,
    encrypt_sensitive,
    encrypt_token,
    validate_encryption_at_startup,
)
from app.core.security import decrypt_credential, encrypt_credential


class EncryptionService:
    """
    Thin façade over AES-256-GCM credential vault.

    Prefer this service from business logic; low-level crypto stays in ``core.crypto``.
    """

    def encrypt(self, value: str) -> str:
        return encrypt_credential(value)

    def decrypt(self, stored: str) -> str:
        return decrypt_credential(stored)

    def encrypt_dict_fields(self, data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        out = dict(data)
        for field in fields:
            val = out.get(field)
            if isinstance(val, str) and val and not val.startswith(AESGCM_PREFIX):
                out[field] = self.encrypt(val)
        return out

    def decrypt_dict_fields(self, data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        out = dict(data)
        for field in fields:
            val = out.get(field)
            if isinstance(val, str) and val:
                out[field] = self.decrypt(val)
        return out


encryption_service = EncryptionService()

__all__ = [
    "EncryptionService",
    "encryption_service",
    "encrypt_token",
    "decrypt_token",
    "encrypt_sensitive",
    "decrypt_sensitive",
    "validate_encryption_at_startup",
]
