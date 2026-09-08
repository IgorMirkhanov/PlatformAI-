"""AES-256-GCM cryptographic utilities for sensitive credential at-rest encryption.

Public API:
  encrypt_token(plain_text) / decrypt_token(cipher_text)

Storage format:
  aesgcm:<urlsafe-base64(nonce || ciphertext+tag)>

Key resolution (first non-empty wins):
  CREDENTIALS_ENCRYPTION_KEY → ENCRYPTION_KEY

Rotation:
  ``CREDENTIALS_ENCRYPTION_KEYS_OLD`` holds a comma-separated list of previously
  active keys. They are used for **decryption only** — writes always use the
  active key — so rotating a key does not orphan rows that were sealed under the
  previous one. Run ``scripts/reencrypt_credentials.py`` to migrate those rows
  onto the active key, then drop the retired entry from the list.

Legacy formats remain readable via ``decrypt_sensitive`` / ``app.core.security``.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from functools import lru_cache
from typing import Final

from loguru import logger

AESGCM_PREFIX: Final[str] = "aesgcm:"
_NONCE_SIZE: Final[int] = 12  # NIST recommended nonce size for AES-GCM
_KEY_SIZE: Final[int] = 32  # AES-256


class EncryptionConfigurationError(RuntimeError):
    """Raised when the encryption key is missing or invalid."""


def _environment_name() -> str:
    return (
        os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("NODE_ENV")
        or "development"
    ).strip().lower()


def is_production_environment() -> bool:
    return _environment_name() in {"production", "prod"}


def resolve_encryption_key_material() -> str | None:
    """
    Prefer ``CREDENTIALS_ENCRYPTION_KEY`` (credential vault contract),
    then fall back to ``ENCRYPTION_KEY``.
    """
    credentials_key = os.getenv("CREDENTIALS_ENCRYPTION_KEY") or None
    if credentials_key and credentials_key.strip():
        return credentials_key.strip()
    primary = os.getenv("ENCRYPTION_KEY") or None
    if primary and primary.strip():
        return primary.strip()
    return None


def _collect_kms_key_materials() -> list[str]:
    """Plaintext KEK materials from ``KMS_KEYS`` (JSON version map)."""
    blob = (os.getenv("KMS_KEYS") or "").strip()
    if not blob:
        return []
    try:
        import json

        parsed = json.loads(blob)
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []
    materials: list[str] = []
    for value in parsed.values():
        material = str(value).strip()
        if material:
            materials.append(material)
    return materials


def resolve_retired_key_materials() -> list[str]:
    """
    Previously active keys, kept readable so a rotation does not orphan rows.

    Sources, in order:

    * ``CREDENTIALS_ENCRYPTION_KEYS_OLD`` (comma-separated)
    * other values in ``KMS_KEYS`` (the versioned vault map)

    Channel tokens use this list; the vault uses ``KMS_KEYS`` directly. A
    rotation that updated the vault map but forgot ``CREDENTIALS_ENCRYPTION_KEYS_OLD``
    used to leave Telegram/WhatsApp tokens unreadable even though the old KEK
    was still configured. The active key is never included; entries are
    deduplicated in declaration order.
    """
    active = resolve_encryption_key_material()
    retired: list[str] = []

    def _add(material: str) -> None:
        value = material.strip()
        if value and value != active and value not in retired:
            retired.append(value)

    raw = (os.getenv("CREDENTIALS_ENCRYPTION_KEYS_OLD") or "").strip()
    if raw:
        for candidate in raw.split(","):
            _add(candidate)

    for material in _collect_kms_key_materials():
        _add(material)

    return retired


def key_fingerprint(raw_secret: str | None) -> str:
    """Short, non-reversible digest of key material — safe to log."""
    if not raw_secret:
        return "unset"
    return hashlib.sha256(raw_secret.strip().encode("utf-8")).hexdigest()[:8]


@lru_cache(maxsize=16)
def derive_aes256_key(raw_secret: str) -> bytes:
    """Normalize env secret material into a strict 32-byte AES key.

    Cached so that per-call encryptors do not re-derive keys — and, with retired
    rotation keys in play, do not re-log the non-32-byte warning on every call.
    """
    candidate = raw_secret.strip().strip("\r")
    if not candidate:
        raise EncryptionConfigurationError("CREDENTIALS_ENCRYPTION_KEY / ENCRYPTION_KEY is empty.")

    # Raw 32-byte UTF-8 secret
    raw_bytes = candidate.encode("utf-8")
    if len(raw_bytes) == _KEY_SIZE:
        return raw_bytes

    # Hex-encoded 32-byte key
    if len(candidate) == 64:
        try:
            decoded = bytes.fromhex(candidate)
            if len(decoded) == _KEY_SIZE:
                return decoded
        except ValueError:
            pass

    # Standard / URL-safe base64 32-byte key (handle missing padding)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            padded = candidate + ("=" * (-len(candidate) % 4))
            decoded = decoder(padded)
            if len(decoded) == _KEY_SIZE:
                return decoded
        except Exception:
            continue

    # Soft-launch convenience: deterministic SHA-256 of passphrase.
    logger.warning(
        "Crypto.key_derived_via_sha256 | "
        "encryption key was not exactly 32 bytes; deriving AES-256 key via SHA-256. "
        "Prefer a dedicated 32-byte key in production."
    )
    return hashlib.sha256(raw_bytes).digest()


class FieldEncryptor:
    """High-level AES-256-GCM encryptor with a unique IV/nonce per encryption run."""

    def __init__(
        self,
        key_material: str | None = None,
        *,
        require_key: bool = False,
        retired_key_materials: list[str] | None = None,
    ) -> None:
        self._key_material = (
            key_material if key_material is not None else resolve_encryption_key_material()
        )
        self._key: bytes | None = None
        if self._key_material:
            self._key = derive_aes256_key(self._key_material)
        elif require_key:
            raise EncryptionConfigurationError(
                "CREDENTIALS_ENCRYPTION_KEY (or ENCRYPTION_KEY) is required for token encryption."
            )

        retired = (
            retired_key_materials
            if retired_key_materials is not None
            else resolve_retired_key_materials()
        )
        # Decryption-only keys, tried in order after the active key.
        self._retired_keys: list[bytes] = [derive_aes256_key(m) for m in retired if m.strip()]

    @property
    def is_configured(self) -> bool:
        return self._key is not None

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext → base64-encoded AES-GCM payload with random IV."""
        if plaintext is None:
            raise ValueError("Cannot encrypt empty credential (None).")
        value = str(plaintext)
        if not value:
            raise ValueError("Cannot encrypt empty credential string.")

        if self._key is None:
            encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
            logger.debug("Crypto.encrypt_dev_plain_fallback")
            return f"plain:{encoded}"

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = secrets.token_bytes(_NONCE_SIZE)
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
        packed = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
        return f"{AESGCM_PREFIX}{packed}"

    def decrypt(self, stored: str) -> str:
        """Decrypt AES-GCM payload. Pass through unrecognized formats for callers."""
        if stored is None:
            raise ValueError("Cannot decrypt empty credential (None).")
        value = str(stored)
        if not value:
            return value

        if value.startswith(AESGCM_PREFIX):
            return self._decrypt_aesgcm(value.removeprefix(AESGCM_PREFIX))

        return value

    def _decrypt_aesgcm(self, packed_b64: str) -> str:
        if self._key is None:
            raise EncryptionConfigurationError(
                "CREDENTIALS_ENCRYPTION_KEY / ENCRYPTION_KEY is required to decrypt aesgcm: credentials."
            )

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        try:
            packed = base64.urlsafe_b64decode(packed_b64 + ("=" * (-len(packed_b64) % 4)))
            if len(packed) <= _NONCE_SIZE:
                raise ValueError("AES-GCM payload too short.")
        except Exception as exc:
            logger.error("Crypto.aesgcm_decode_failed | error={error}", error=str(exc))
            raise ValueError("Failed to decrypt AES-GCM credential payload.") from exc

        nonce, ciphertext = packed[:_NONCE_SIZE], packed[_NONCE_SIZE:]
        last_error: Exception | None = None
        # Active key first, then retired keys so a rotation stays readable.
        for index, key in enumerate([self._key, *self._retired_keys]):
            try:
                plaintext = AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
            except Exception as exc:  # noqa: PERF203 - per-key trial is the point
                last_error = exc
                continue
            if index > 0:
                logger.warning(
                    "Crypto.aesgcm_decrypted_with_retired_key | retired_key_index={index} "
                    "hint=run scripts/reencrypt_credentials.py to migrate onto the active key",
                    index=index,
                )
            return plaintext

        logger.error(
            "Crypto.aesgcm_decrypt_failed | keys_tried={tried} error={error}",
            tried=1 + len(self._retired_keys),
            error=str(last_error),
        )
        raise ValueError("Failed to decrypt AES-GCM credential payload.") from last_error


_encryptor: FieldEncryptor | None = None


def get_field_encryptor() -> FieldEncryptor:
    global _encryptor
    if _encryptor is None:
        _encryptor = FieldEncryptor()
    return _encryptor


def reset_field_encryptor() -> None:
    """Test helper — clear cached encryptor so env changes are picked up."""
    global _encryptor
    _encryptor = None
    derive_aes256_key.cache_clear()


def encrypt_token(plain_text: str) -> str:
    """
    Encrypt a user credential / API token with AES-256-GCM.

    Requires ``CREDENTIALS_ENCRYPTION_KEY`` (or ``ENCRYPTION_KEY``) in production.
    Returns ``aesgcm:<urlsafe-b64(nonce||ciphertext+tag)>``.
    """
    material = resolve_encryption_key_material()
    if not material and is_production_environment():
        raise EncryptionConfigurationError(
            "CREDENTIALS_ENCRYPTION_KEY is required to encrypt credentials in production."
        )
    encryptor = FieldEncryptor(material, require_key=bool(material) or is_production_environment())
    return encryptor.encrypt(plain_text)


def decrypt_token(cipher_text: str) -> str:
    """
    Decrypt an AES-256-GCM credential payload produced by ``encrypt_token``.

    Also accepts legacy ``plain:`` / raw strings for soft-launch rows.
    """
    if not cipher_text:
        return cipher_text

    value = str(cipher_text)
    if value.startswith(AESGCM_PREFIX):
        material = resolve_encryption_key_material()
        if not material:
            raise EncryptionConfigurationError(
                "CREDENTIALS_ENCRYPTION_KEY is required to decrypt aesgcm: credentials."
            )
        return FieldEncryptor(material, require_key=True).decrypt(value)

    if value.startswith("plain:"):
        try:
            return base64.urlsafe_b64decode(
                value.removeprefix("plain:").encode("ascii") + b"==="
            ).decode("utf-8")
        except Exception as exc:
            raise ValueError("Corrupt plain: credential payload.") from exc

    # Unprefixed plaintext (legacy) — return as-is.
    return value


def encrypt_sensitive(value: str) -> str:
    """Backward-compatible alias used across the codebase."""
    try:
        return encrypt_token(value)
    except EncryptionConfigurationError:
        # Dev soft-launch path when no key is configured.
        return get_field_encryptor().encrypt(value)


def decrypt_sensitive(stored: str) -> str:
    """Decrypt AES-GCM values; pass through unrecognized formats for graceful fallbacks."""
    try:
        if isinstance(stored, str) and stored.startswith(AESGCM_PREFIX):
            return decrypt_token(stored)
        return stored
    except Exception as exc:
        logger.warning(
            "Crypto.decrypt_sensitive_passthrough | error={error}",
            error=str(exc),
        )
        return stored


def looks_encrypted(stored: str | None) -> bool:
    if not stored or not isinstance(stored, str):
        return False
    return stored.startswith(AESGCM_PREFIX) or stored.startswith("enc:") or stored.startswith("plain:")


def validate_encryption_at_startup() -> None:
    """
    Halt boot in production when crypto/JWT secrets are missing or unusable.

    Validates:
      1. AES-256-GCM key material (CREDENTIALS_ENCRYPTION_KEY / ENCRYPTION_KEY)
      2. Round-trip encrypt/decrypt self-test
      3. Optional Fernet key (CREDENTIALS_ENCRYPTION_KEY as urlsafe 32-byte) when present
      4. JWT_SECRET_KEY availability in production
    """
    material = resolve_encryption_key_material()
    production = is_production_environment()

    if production and not material:
        message = (
            "FATAL: CREDENTIALS_ENCRYPTION_KEY (or ENCRYPTION_KEY) is required in production. "
            "Provide a 32-byte secret (raw, hex, or base64) via the environment file."
        )
        logger.error(message)
        raise EncryptionConfigurationError(message)

    if not material:
        logger.warning(
            "Crypto.startup_dev_mode | encryption key unset — "
            "credentials will use reversible plain: storage. Not safe for production."
        )
    else:
        try:
            key = derive_aes256_key(material)
            token = encrypt_token("mpai-encryption-self-test")
            recovered = decrypt_token(token)
            if recovered != "mpai-encryption-self-test" or len(key) != _KEY_SIZE:
                raise EncryptionConfigurationError("Encryption key self-test failed.")
            retired = resolve_retired_key_materials()
            # Truncated digest, never the key: makes an unintended key swap (a stray
            # shell export overriding env_file, a wrong .env) visible in the logs
            # instead of surfacing later as undecryptable rows.
            logger.info(
                "Crypto.startup_ok | algorithm=AES-256-GCM production={production} "
                "retired_keys={retired} key_fingerprint={fingerprint} environment={env}",
                production=production,
                retired=len(retired),
                fingerprint=key_fingerprint(material),
                env=_environment_name(),
            )
            if retired:
                logger.warning(
                    "Crypto.rotation_pending | {count} retired key(s) still needed for reads — "
                    "run scripts/reencrypt_credentials.py, then clear "
                    "CREDENTIALS_ENCRYPTION_KEYS_OLD",
                    count=len(retired),
                )
        except EncryptionConfigurationError:
            raise
        except Exception as exc:
            message = f"FATAL: encryption key is misconfigured — {exc}"
            logger.error(message)
            if production:
                raise EncryptionConfigurationError(message) from exc
            logger.warning("Crypto.startup_key_warning | error={error}", error=str(exc))

        # Fernet dual-path: if CREDENTIALS_ENCRYPTION_KEY is a valid Fernet key, verify it.
        fernet_material = (os.getenv("CREDENTIALS_ENCRYPTION_KEY") or "").strip()
        if fernet_material:
            try:
                from cryptography.fernet import Fernet

                fernet_key = fernet_material.encode("utf-8")
                # Accept either a real Fernet key or derive one for soft-launch passphrases.
                try:
                    fernet = Fernet(fernet_key)
                except Exception:
                    derived = base64.urlsafe_b64encode(hashlib.sha256(fernet_key).digest())
                    fernet = Fernet(derived)
                probe = fernet.encrypt(b"mpai-fernet-self-test")
                if fernet.decrypt(probe) != b"mpai-fernet-self-test":
                    raise EncryptionConfigurationError("Fernet self-test failed.")
                logger.info("Crypto.fernet_ok | legacy_enc_prefix_supported=true")
            except EncryptionConfigurationError:
                raise
            except Exception as exc:
                msg = f"Fernet key validation failed: {exc}"
                if production:
                    logger.error("Crypto.fernet_fatal | error={error}", error=msg)
                    raise EncryptionConfigurationError(msg) from exc
                logger.warning("Crypto.fernet_warning | error={error}", error=msg)

    # JWT secret must be explicit and distinct from credential encryption keys (§2.2).
    jwt_secret = (os.getenv("JWT_SECRET_KEY") or "").strip()
    enc_material = (
        os.getenv("ENCRYPTION_KEY") or os.getenv("CREDENTIALS_ENCRYPTION_KEY") or ""
    ).strip()
    if production and not jwt_secret:
        message = "FATAL: JWT_SECRET_KEY is required in production (no encryption-key fallback)."
        logger.error(message)
        raise EncryptionConfigurationError(message)
    if production and jwt_secret and enc_material and jwt_secret == enc_material:
        message = (
            "FATAL: JWT_SECRET_KEY must differ from ENCRYPTION_KEY / CREDENTIALS_ENCRYPTION_KEY."
        )
        logger.error(message)
        raise EncryptionConfigurationError(message)
    if jwt_secret:
        logger.info("Crypto.jwt_secret_ok | configured=true distinct_from_encryption=true")
    else:
        logger.warning("Crypto.jwt_secret_missing | JWT minting will fail until configured")
