"""AES-256-GCM encrypt(text) / decrypt(text) for Integration Hub secrets.

Key material: ``ENCRYPTION_KEY`` — 32-byte key, typically base64-encoded.
Never log plaintext or decrypted values.
"""

from __future__ import annotations

import os

from loguru import logger
from pydantic import SecretStr

from app.core.crypto import (
    EncryptionConfigurationError,
    decrypt_token,
    derive_aes256_key,
    encrypt_token,
    resolve_encryption_key_material,
)


class EncryptionError(RuntimeError):
    """Raised when Hub encrypt/decrypt cannot run."""


def _require_key_material() -> str:
    material = (os.getenv("ENCRYPTION_KEY") or "").strip() or resolve_encryption_key_material()
    if not material:
        raise EncryptionError(
            "ENCRYPTION_KEY is required (32-byte key, base64 or hex). "
            "Do not store the key in source."
        )
    key = derive_aes256_key(material)
    if len(key) != 32:
        raise EncryptionError("ENCRYPTION_KEY must resolve to 32 bytes for AES-256-GCM.")
    return material


def encrypt(text: str) -> str:
    """Encrypt a secret string. Return value is safe to persist; never log ``text``."""
    if text is None or str(text) == "":
        raise EncryptionError("Cannot encrypt empty secret.")
    try:
        _require_key_material()
        return encrypt_token(str(text))
    except (EncryptionConfigurationError, EncryptionError):
        raise
    except Exception as exc:
        logger.error("Encryption.encrypt_failed | error={error}", error=type(exc).__name__)
        raise EncryptionError("Failed to encrypt secret.") from exc


def decrypt(text: str) -> str:
    """Decrypt a Hub ciphertext. Caller must not log the return value."""
    if not text:
        return ""
    try:
        _require_key_material()
        secret = SecretStr(decrypt_token(str(text)))
        return secret.get_secret_value()
    except (EncryptionConfigurationError, EncryptionError):
        raise
    except Exception as exc:
        logger.error("Encryption.decrypt_failed | error={error}", error=type(exc).__name__)
        raise EncryptionError("Failed to decrypt secret.") from exc


__all__ = ["EncryptionError", "decrypt", "encrypt"]
