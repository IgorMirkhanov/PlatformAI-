"""Password hashing, JWT access tokens, and credential encryption utilities.

Primary at-rest algorithm: AES-256-GCM via ``app.core.crypto``.
Legacy Fernet (``enc:``) and soft-launch (``plain:``) payloads remain readable.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from loguru import logger

from app.core.config import settings
from app.core.crypto import (
    AESGCM_PREFIX,
    decrypt_sensitive,
    decrypt_token,
    encrypt_sensitive,
    encrypt_token,
    looks_encrypted,
)


class TokenError(Exception):
    """Raised when a JWT cannot be created or verified."""


def hash_bot_token(token: str) -> str:
    """Return a stable SHA-256 hex digest used for webhook URL routing."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def encrypt_credential(value: str) -> str:
    """Encrypt a sensitive credential for database storage (AES-256-GCM)."""
    try:
        return encrypt_token(value)
    except Exception as exc:
        logger.error("Security.encrypt_credential_failed | error={error}", error=str(exc))
        try:
            return encrypt_sensitive(value)
        except Exception as inner:
            if settings.is_production or not settings.ALLOW_PLAIN_CREDENTIAL_FALLBACK:
                raise RuntimeError(
                    "Failed to encrypt credential; configure CREDENTIALS_ENCRYPTION_KEY "
                    "or set ALLOW_PLAIN_CREDENTIAL_FALLBACK=true only for local dev."
                ) from inner
            encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
            logger.warning("Security.encrypt_credential_plain_fallback_dev")
            return f"plain:{encoded}"


def decrypt_credential(stored: str) -> str:
    """Decrypt a stored credential with graceful fallback for legacy plaintext rows."""
    if not stored:
        return stored

    value = str(stored)

    # New AES-256-GCM payloads
    if value.startswith(AESGCM_PREFIX):
        try:
            return decrypt_token(value)
        except Exception as exc:
            logger.error(
                "Security.decrypt_aesgcm_failed | error={error}",
                error=str(exc),
            )
            raise

    # Legacy Fernet
    if value.startswith("enc:"):
        key = settings.CREDENTIALS_ENCRYPTION_KEY
        if not key:
            logger.error("Security.decrypt_fernet_missing_key")
            raise RuntimeError(
                "CREDENTIALS_ENCRYPTION_KEY is required to decrypt legacy enc: credentials"
            )
        try:
            from cryptography.fernet import Fernet

            fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
            return fernet.decrypt(value.removeprefix("enc:").encode("ascii")).decode("utf-8")
        except Exception as exc:
            logger.warning(
                "Security.decrypt_fernet_fallback | error={error}",
                error=str(exc),
            )
            # Graceful fallback for corrupted/legacy rows — return raw for diagnostics
            # only if it does not look ciphertext-like.
            if looks_encrypted(value):
                raise
            return value

    if value.startswith("plain:"):
        if settings.is_production:
            raise RuntimeError(
                "plain: credential payloads are forbidden in production — re-encrypt the row."
            )
        try:
            return decrypt_token(value)
        except Exception:
            try:
                return base64.urlsafe_b64decode(
                    value.removeprefix("plain:").encode("ascii") + b"==="
                ).decode("utf-8")
            except Exception as exc:
                logger.warning(
                    "Security.decrypt_plain_corrupt | error={error}",
                    error=str(exc),
                )
                return value.removeprefix("plain:")

    # Unencrypted historical test records — pass through without raising.
    logger.debug("Security.decrypt_passthrough_plaintext")
    return value


def hash_password(password: str) -> str:
    """Hash a user password (bcrypt preferred; sha256 legacy still verifiable)."""
    try:
        import bcrypt

        digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
        return f"bcrypt:{digest.decode('ascii')}"
    except Exception:
        salt = secrets.token_hex(16)
        digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
        return f"sha256:{salt}:{digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against ``hash_password`` / legacy digests."""
    if not stored_hash:
        return False

    if stored_hash.startswith("bcrypt:"):
        try:
            import bcrypt

            raw = stored_hash.removeprefix("bcrypt:").encode("ascii")
            return bcrypt.checkpw(password.encode("utf-8"), raw)
        except Exception:
            return False

    if stored_hash.startswith("sha256:"):
        try:
            _, salt, digest = stored_hash.split(":", 2)
        except ValueError:
            return False
        candidate = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
        return secrets.compare_digest(candidate, digest)

    # fastapi-users / passlib raw bcrypt hashes (no prefix)
    if stored_hash.startswith("$2"):
        try:
            import bcrypt

            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("ascii"))
        except Exception:
            return False

    return False


def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)


def _jwt_secret() -> str:
    secret = settings.JWT_SECRET_KEY
    if secret and str(secret).strip():
        return str(secret).strip()
    # Soft-launch / local: allow a deterministic secret so auth works without
    # forcing every developer to mint keys before first login.
    if not settings.is_production:
        logger.warning(
            "Security.jwt_secret_fallback | using development JWT secret — "
            "set JWT_SECRET_KEY in .env before production"
        )
        return "mpai-dev-jwt-secret-change-me-before-prod"
    raise TokenError(
        "JWT_SECRET_KEY is required to mint/verify access tokens."
    )


def create_access_token(
    *,
    subject: uuid.UUID | str,
    company_id: uuid.UUID | str | None = None,
    role: str | None = None,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Mint a standard HS256 JWT access token (no proprietary prefixes).

    Claims:
      sub, company_id?, role?, iat, exp, typ=access
    """
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "typ": "access",
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if company_id is not None:
        payload["company_id"] = str(company_id)
    if role is not None:
        payload["role"] = str(role)
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and verify a standard JWT access token.

    Expects a bare JWT string (no ``Bearer `` / ``imp_`` prefixes).
    Raises ``TokenError`` on any validation failure.
    """
    if not token or not isinstance(token, str):
        raise TokenError("Missing access token.")

    raw = token.strip()
    if raw.lower().startswith("bearer "):
        raw = raw.split(" ", 1)[1].strip()
    if raw.startswith("imp_"):
        raise TokenError("Impersonation tokens must be handled separately.")

    try:
        payload = jwt.decode(
            raw,
            _jwt_secret(),
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid access token.") from exc

    if not isinstance(payload, dict):
        raise TokenError("Malformed access token payload.")

    token_type = payload.get("typ")
    if token_type is not None and token_type not in {"access", "impersonation"}:
        raise TokenError("Unexpected token type.")

    return payload


def create_impersonation_token(
    *,
    target_user_id: uuid.UUID | str,
    admin_user_id: uuid.UUID | str,
    company_id: uuid.UUID | str | None = None,
    role: str | None = None,
    expires_delta: timedelta | None = None,
    jti: str | None = None,
) -> str:
    """Mint a JWT used only for support impersonation sessions (typ=impersonation)."""
    return create_access_token(
        subject=target_user_id,
        company_id=company_id,
        role=role,
        expires_delta=expires_delta or timedelta(hours=1),
        extra_claims={
            "typ": "impersonation",
            "impersonated_by": str(admin_user_id),
            "impersonator_id": str(admin_user_id),
            "jti": jti or str(uuid.uuid4()),
        },
    )
