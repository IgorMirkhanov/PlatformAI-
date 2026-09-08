"""Shared Admin Panel helpers (tokens, role checks, response builders)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.admin import PlatformRole, platform_role_of
from app.core.config import settings
from app.core.security import create_impersonation_token, verify_password
from app.models.core_models import Company, DiagnosticErrorType
from app.models.users import User
from app.schemas.admin import ImpersonationResponse
from app.services.audit_service import audit_service

IMPERSONATION_TTL_SECONDS = 60 * 60  # 1 hour
ACTION_START = "IMPERSONATION_START"
ACTION_END = "IMPERSONATION_END"
ACTION_BALANCE_ADJUST = "BALANCE_ADJUST"
ACTION_BOT_BALANCE_ADJUST = "BOT_BALANCE_ADJUST"
ACTION_BOT_SUBSCRIPTION = "BOT_SUBSCRIPTION"


def diagnostic_level(error_type: DiagnosticErrorType | str) -> str:
    raw = error_type.value if isinstance(error_type, DiagnosticErrorType) else str(error_type)
    warning_types = {
        DiagnosticErrorType.RAG_EMPTY.value,
        DiagnosticErrorType.INSUFFICIENT_FUNDS.value,
    }
    if raw in warning_types:
        return "WARNING"
    return "ERROR"


def public_tx_status(status_value: object) -> str:
    raw = status_value.value if hasattr(status_value, "value") else str(status_value)
    mapping = {
        "SUCCESS": "succeeded",
        "APPROVED": "succeeded",
        "PENDING": "pending",
        "FAILED": "failed",
        "REJECTED": "failed",
    }
    return mapping.get(str(raw).upper(), str(raw).lower())


def _impersonation_secret() -> bytes:
    raw = getattr(settings, "IMPERSONATION_HMAC_SECRET", None) or settings.JWT_SECRET_KEY
    if not raw:
        if settings.is_production:
            raise RuntimeError(
                "IMPERSONATION_HMAC_SECRET or JWT_SECRET_KEY is required in production."
            )
        raw = "dev-impersonation-secret"
        logger.warning("Admin.impersonation_using_dev_secret")
    return hashlib.sha256(str(raw).encode("utf-8")).digest()


def assert_admin_reauth(*, admin: User, password: str) -> None:
    """Step-up: require the actor's password immediately before impersonation."""
    if not password or not str(password).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin password confirmation is required before impersonation.",
        )
    if not verify_password(str(password), getattr(admin, "hashed_password", "") or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password. Re-authentication required to impersonate.",
        )


def mint_legacy_impersonation_token(
    *,
    actor_user_id: uuid.UUID,
    organization_id: uuid.UUID,
    target_user_id: uuid.UUID,
    ttl_seconds: int = IMPERSONATION_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Legacy ``imp_*`` HMAC token (kept for BC with older clients)."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    payload = {
        "typ": "impersonation",
        "actor_user_id": str(actor_user_id),
        "impersonated_by": str(actor_user_id),
        "organization_id": str(organization_id),
        "target_user_id": str(target_user_id),
        "exp": int(expires_at.timestamp()),
    }
    body = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    signature = hmac.new(
        _impersonation_secret(),
        body.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"imp_{body}.{signature}", expires_at


# Public aliases used by middleware / rbac.
mint_impersonation_token = mint_legacy_impersonation_token


def decode_impersonation_token(token: str) -> dict[str, object] | None:
    if not token or not token.startswith("imp_"):
        return None
    try:
        body, signature = token.removeprefix("imp_").rsplit(".", 1)
    except ValueError:
        return None

    expected = hmac.new(
        _impersonation_secret(),
        body.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None

    padding = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + padding).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None

    if payload.get("typ") != "impersonation":
        return None

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(datetime.now(timezone.utc).timestamp()):
        return None

    return payload


def require_platform_admin(user: User) -> None:
    role = platform_role_of(user)
    if role not in {PlatformRole.SUPERADMIN, PlatformRole.SUPPORT}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges are required for this action.",
        )


def assert_impersonation_allowed(*, admin: User, target_user: User) -> None:
    if target_user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot impersonate your own admin account.",
        )
    if bool(getattr(target_user, "is_superadmin", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot impersonate a SUPERADMIN account.",
        )
    if bool(getattr(target_user, "is_support", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot impersonate a SUPPORT staff account.",
        )
    if not bool(getattr(target_user, "is_active", True)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot impersonate an inactive user.",
        )


async def build_impersonation_response(
    db: AsyncSession,
    *,
    admin: User,
    target_user: User,
    request: Request,
) -> ImpersonationResponse:
    organization_id = target_user.company_id
    company = await db.get(Company, organization_id)
    organization_name = company.name if company is not None else target_user.company_name

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=IMPERSONATION_TTL_SECONDS)
    jti = str(uuid.uuid4())
    await audit_service.write(
        db,
        admin_id=admin.id,
        target_user_id=target_user.id,
        action=ACTION_START,
        organization_id=organization_id,
        ip_address=audit_service.client_ip(request),
        details={
            "token_typ": "impersonation",
            "ttl_seconds": IMPERSONATION_TTL_SECONDS,
            "jti": jti,
            "step_up": "password",
        },
    )

    # Primary: JWT with impersonated_by + jti (revocable via Redis denylist).
    access_token = create_impersonation_token(
        target_user_id=target_user.id,
        admin_user_id=admin.id,
        company_id=organization_id,
        role=target_user.role.value if target_user.role else None,
        expires_delta=timedelta(seconds=IMPERSONATION_TTL_SECONDS),
        jti=jti,
    )

    logger.warning(
        "Admin.impersonate_start | actor={actor} target={target} email={email} ip={ip}",
        actor=admin.id,
        target=target_user.id,
        email=target_user.email,
        ip=audit_service.client_ip(request),
    )

    return ImpersonationResponse(
        access_token=access_token,
        organization_id=organization_id,
        organization_name=organization_name,
        impersonated_user_id=target_user.id,
        impersonated_user_email=target_user.email,
        impersonated_user_name=target_user.full_name or "",
        impersonated_user_role=target_user.role.value if target_user.role else "OWNER",
        impersonated_by=admin.id,
        expires_at=expires_at,
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-User-Id": str(target_user.id),
            "X-Company-Id": str(organization_id),
        },
        message=f"Вошли под аккаунтом {target_user.email}.",
    )
