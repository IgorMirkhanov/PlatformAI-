"""Shared webhook authentication helpers (Meta HMAC, Telegram secret, internal key)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from fastapi import HTTPException, Request, status
from loguru import logger

from app.core.config import settings
from app.core.tenant import has_internal_service_key


def meta_app_secret() -> str:
    """Meta / Facebook app secret used for X-Hub-Signature-256 verification."""
    return (
        (getattr(settings, "META_APP_SECRET", None) or "")
        or (getattr(settings, "FACEBOOK_APP_SECRET", None) or "")
        or (getattr(settings, "WHATSAPP_APP_SECRET", None) or "")
        or ""
    ).strip()


def verify_meta_signature(
    raw_body: bytes,
    signature_header: str | None,
    *,
    app_secret: str | None = None,
) -> bool:
    """
    Verify Meta ``X-Hub-Signature-256: sha256=<hex>`` against the raw request body.

    Returns False (never raises) when the signature is missing or mismatched.
    """
    secret = (app_secret if app_secret is not None else meta_app_secret()).strip()
    if not secret:
        # Fail closed in production; allow unsigned in local/dev when secret unset.
        if settings.is_production:
            logger.error("WebhookAuth.meta_secret_missing")
            return False
        logger.warning("WebhookAuth.meta_secret_unset_dev_bypass")
        return True

    header = (signature_header or "").strip()
    if not header.lower().startswith("sha256="):
        return False
    provided = header.split("=", 1)[1].strip()
    if not provided:
        return False

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return secrets.compare_digest(expected, provided)


def require_meta_signature(request: Request, raw_body: bytes) -> None:
    """Raise 403 when Meta signature verification fails."""
    header = request.headers.get("x-hub-signature-256") or request.headers.get("x-hub-signature")
    if not verify_meta_signature(raw_body, header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Meta webhook signature.",
        )


def require_internal_service_key(request: Request) -> None:
    """Raise 403 unless ``X-Internal-Api-Key`` matches configured secret."""
    if has_internal_service_key(request):
        return
    expected = (getattr(settings, "INTERNAL_SERVICE_API_KEY", None) or "").strip()
    if not expected and not settings.is_production:
        logger.warning("WebhookAuth.internal_key_unset_dev_bypass")
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Internal service authentication required.",
    )


def verify_telegram_secret_token(
    provided_header: str | None,
    expected_secret: str | None,
) -> bool:
    """Constant-time compare of Telegram ``X-Telegram-Bot-Api-Secret-Token``."""
    ok, _reason = verify_telegram_secret_token_detailed(provided_header, expected_secret)
    return ok


def verify_telegram_secret_token_detailed(
    provided_header: str | None,
    expected_secret: str | None,
) -> tuple[bool, str]:
    """
    Return ``(ok, reason)`` for Telegram secret-token checks.

    Reasons are safe for logs (no secret values):
    ``ok``, ``missing_stored_secret``, ``missing_header``, ``secret_mismatch``.
    """
    expected = (expected_secret or "").strip()
    provided = (provided_header or "").strip()
    if not expected:
        if settings.is_production:
            return False, "missing_stored_secret"
        # Legacy bots without a stored secret — allow only outside production.
        return True, "ok_dev_bypass_no_stored_secret"
    if not provided:
        return False, "missing_header"
    if not secrets.compare_digest(provided, expected):
        return False, "secret_mismatch"
    return True, "ok"


def extract_telegram_webhook_secret(credentials: dict[str, Any] | None) -> str | None:
    """Pull stored Telegram webhook secret_token from bot credentials JSON."""
    if not isinstance(credentials, dict):
        return None
    direct = credentials.get("webhook_secret_token") or credentials.get("telegram_webhook_secret")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    channels = credentials.get("channels")
    if isinstance(channels, dict):
        for key in ("telegram", "telegram_business"):
            block = channels.get(key)
            if isinstance(block, dict):
                secret = block.get("webhook_secret_token") or block.get("telegram_webhook_secret")
                if isinstance(secret, str) and secret.strip():
                    return secret.strip()
    return None


async def resolve_telegram_webhook_secret_for_bot(
    db: Any,
    bot: Any,
) -> str | None:
    """
    Resolve Telegram webhook secret from bot credentials, then BotChannel.meta_data.

    Path secret in ``/webhooks/telegram/{token_hash}`` identifies the bot; the
    ``X-Telegram-Bot-Api-Secret-Token`` header must match the secret stored when
    ``setWebhook`` was called.
    """
    credentials = bot.credentials if isinstance(getattr(bot, "credentials", None), dict) else None
    secret = extract_telegram_webhook_secret(credentials)
    if secret:
        return secret

    try:
        from sqlalchemy import select

        from app.models.channels import BotChannel, HubChannelType

        result = await db.execute(
            select(BotChannel).where(
                BotChannel.bot_id == bot.id,
                BotChannel.channel_type.in_(
                    [HubChannelType.TELEGRAM, HubChannelType.TELEGRAM_BUSINESS]
                ),
            )
        )
        for row in result.scalars().all():
            meta = row.meta_data if isinstance(row.meta_data, dict) else {}
            candidate = meta.get("webhook_secret_token") or meta.get("telegram_webhook_secret")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    except Exception as exc:
        logger.warning(
            "WebhookAuth.channel_secret_lookup_failed | bot_id={bot_id} error={error}",
            bot_id=getattr(bot, "id", None),
            error=str(exc),
        )
    return None
