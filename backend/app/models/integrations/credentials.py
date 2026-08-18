"""CRM integration credential encryption helpers (amoCRM / Bitrix24).

Sensitive OAuth tokens and webhook secrets are sealed with AES-256-GCM before
they are written into ``bot.credentials["crm"]`` and decrypted on read for
Celery CRM workers and sync routers.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.core.security import decrypt_credential, encrypt_credential
from app.models.core_models import Bot

_SENSITIVE_AMOCRM_FIELDS = ("access_token", "refresh_token", "client_secret", "api_key")
_SENSITIVE_BITRIX_FIELDS = ("webhook_url", "access_token", "api_key")


def _safe_decrypt(value: Any, *, field: str) -> Any:
    if value is None or not isinstance(value, str) or value == "":
        return value
    try:
        return decrypt_credential(value)
    except Exception as exc:
        logger.warning(
            "IntegrationCredentials.decrypt_fallback | field={field} error={error}",
            field=field,
            error=str(exc),
        )
        return value


def _safe_encrypt(value: Any) -> Any:
    if value is None or not isinstance(value, str) or value == "":
        return value
    if value.startswith(("aesgcm:", "enc:", "plain:")):
        return value
    return encrypt_credential(value)


def seal_amocrm_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of amoCRM config with sensitive fields encrypted."""
    sealed = dict(config)
    for field in _SENSITIVE_AMOCRM_FIELDS:
        if field in sealed and sealed[field]:
            sealed[field] = _safe_encrypt(sealed[field])
    return sealed


def reveal_amocrm_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return amoCRM config with sensitive fields decrypted for runtime use."""
    if not isinstance(config, dict):
        return config
    revealed = dict(config)
    for field in _SENSITIVE_AMOCRM_FIELDS:
        if field in revealed and revealed[field]:
            revealed[field] = _safe_decrypt(revealed[field], field=field)
    return revealed


def seal_bitrix_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of Bitrix24 config with webhook/api secrets encrypted."""
    sealed = dict(config)
    for field in _SENSITIVE_BITRIX_FIELDS:
        if field in sealed and sealed[field]:
            sealed[field] = _safe_encrypt(sealed[field])
    return sealed


def reveal_bitrix_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return Bitrix24 config with secrets decrypted for runtime webhook calls."""
    if not isinstance(config, dict):
        return config
    revealed = dict(config)
    for field in _SENSITIVE_BITRIX_FIELDS:
        if field in revealed and revealed[field]:
            revealed[field] = _safe_decrypt(revealed[field], field=field)
    return revealed


def get_amocrm_access_token(bot: Bot) -> str | None:
    crm = (bot.credentials or {}).get("crm") if isinstance(bot.credentials, dict) else {}
    config = reveal_amocrm_config(crm.get("amocrm") if isinstance(crm, dict) else None)
    if not config:
        return None
    token = config.get("access_token")
    return str(token) if token else None


def get_bitrix_webhook_url(bot: Bot) -> str | None:
    crm = (bot.credentials or {}).get("crm") if isinstance(bot.credentials, dict) else {}
    config = reveal_bitrix_config(crm.get("bitrix24") if isinstance(crm, dict) else None)
    if not config or not config.get("connected"):
        return None
    url = config.get("webhook_url")
    if isinstance(url, str) and url.strip():
        return url.rstrip("/") + "/"
    return None


__all__ = [
    "seal_amocrm_config",
    "reveal_amocrm_config",
    "seal_bitrix_config",
    "reveal_bitrix_config",
    "get_amocrm_access_token",
    "get_bitrix_webhook_url",
]
