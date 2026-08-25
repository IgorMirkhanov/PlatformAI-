"""AES-256-GCM payload encryption with KEK versioning (architecture spec §2)."""

from __future__ import annotations

import base64
import json
import os
import secrets
from typing import Any, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from app.core.crypto import derive_aes256_key, resolve_encryption_key_material

_NONCE_SIZE: Final[int] = 12
_TAG_SIZE: Final[int] = 16
_FIELD_ALG: Final[str] = "AESGCM"


class CredentialSecret(SecretStr):
    """Pydantic wrapper so decrypted credentials never stringify into logs/Sentry."""


def current_key_version() -> int:
    raw = (os.getenv("CREDENTIALS_KEY_VERSION") or os.getenv("KMS_CURRENT_VERSION") or "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _load_kms_keys() -> dict[int, bytes]:
    keys: dict[int, bytes] = {}
    blob = (os.getenv("KMS_KEYS") or "").strip()
    if blob:
        parsed = json.loads(blob)
        if isinstance(parsed, dict):
            for version, material in parsed.items():
                keys[int(version)] = derive_aes256_key(str(material))
    master = (os.getenv("MASTER_ENCRYPTION_KEY") or "").strip() or resolve_encryption_key_material()
    if master:
        keys.setdefault(1, derive_aes256_key(master))
        keys.setdefault(current_key_version(), derive_aes256_key(master))
    return keys


def _kek(version: int) -> bytes:
    keys = _load_kms_keys()
    key = keys.get(version)
    if key is None:
        raise RuntimeError(f"No KEK configured for key_version={version}")
    return key


def encrypt_payload(plaintext: dict[str, Any], kek: bytes | None = None) -> tuple[bytes, bytes, bytes]:
    """Return (ciphertext_without_tag, iv, tag)."""
    key = kek if kek is not None else _kek(current_key_version())
    nonce = secrets.token_bytes(_NONCE_SIZE)
    packed = AESGCM(key).encrypt(nonce, json.dumps(plaintext, ensure_ascii=False).encode("utf-8"), None)
    ciphertext, tag = packed[:-_TAG_SIZE], packed[-_TAG_SIZE:]
    return ciphertext, nonce, tag


def decrypt_payload(
    ciphertext: bytes,
    iv: bytes,
    tag: bytes,
    kek: bytes | None = None,
    *,
    key_version: int = 1,
) -> dict[str, Any]:
    key = kek if kek is not None else _kek(key_version)
    packed = bytes(ciphertext) + bytes(tag)
    raw = AESGCM(key).decrypt(bytes(iv), packed, None)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Decrypted credential payload is not an object")
    return payload


def decrypt_secret(
    ciphertext: bytes,
    iv: bytes,
    tag: bytes,
    *,
    key_version: int = 1,
) -> CredentialSecret:
    data = decrypt_payload(ciphertext, iv, tag, key_version=key_version)
    secret = str(data.get("api_key") or data.get("token") or data.get("access_token") or "")
    return CredentialSecret(secret)


def encrypt_field(value: str) -> str:
    """Envelope-encrypt a string for Text columns (OAuth client_secret). Key from ENV/KMS."""
    ciphertext, iv, tag = encrypt_payload({"value": value})
    envelope = {
        "alg": _FIELD_ALG,
        "kv": current_key_version(),
        "ct": base64.b64encode(ciphertext).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }
    return json.dumps(envelope, separators=(",", ":"))


def decrypt_field(blob: str | None) -> str:
    """Decrypt ``encrypt_field`` envelope; also accepts legacy ``aesgcm:`` tokens."""
    raw = (blob or "").strip()
    if not raw:
        return ""
    if raw.startswith("aesgcm:"):
        from app.core.crypto import decrypt_token

        return decrypt_token(raw)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Encrypted field envelope is not an object")
    ciphertext = base64.b64decode(str(data.get("ct") or ""))
    iv = base64.b64decode(str(data.get("iv") or ""))
    tag = base64.b64decode(str(data.get("tag") or ""))
    payload = decrypt_payload(ciphertext, iv, tag, key_version=int(data.get("kv") or 1))
    return str(payload.get("value") or "")


__all__ = [
    "CredentialSecret",
    "InvalidTag",
    "current_key_version",
    "decrypt_field",
    "decrypt_payload",
    "decrypt_secret",
    "encrypt_field",
    "encrypt_payload",
]
