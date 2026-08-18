"""Bot model credential accessors with transparent AES-256 field encryption.

Sensitive channel tokens live inside ``bots.credentials`` JSONB. These property
wrappers encrypt on write and decrypt on read so Celery workers and API handlers
always receive plaintext tokens without caring about storage encoding.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import String, TypeDecorator

from app.core.security import decrypt_credential, encrypt_credential
from app.models.core_models import Bot as BotModel


class EncryptedString(TypeDecorator[str]):
    """SQLAlchemy column type that transparently AES-encrypts string values."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None or value == "":
            return value
        # Avoid double-encrypting already sealed payloads.
        if isinstance(value, str) and value.startswith(("aesgcm:", "enc:", "plain:")):
            return value
        return encrypt_credential(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        if value is None or value == "":
            return value
        try:
            return decrypt_credential(value)
        except Exception as exc:
            logger.warning(
                "EncryptedString.decrypt_fallback | error={error}",
                error=str(exc),
            )
            return value


def _credentials_dict(bot: BotModel) -> dict[str, Any]:
    raw = bot.credentials
    return dict(raw) if isinstance(raw, dict) else {}


def _telegram_channel(credentials: dict[str, Any]) -> dict[str, Any]:
    channels = credentials.get("channels")
    if not isinstance(channels, dict):
        return {}
    telegram = channels.get("telegram")
    return dict(telegram) if isinstance(telegram, dict) else {}


def get_telegram_bot_token(bot: BotModel) -> str:
    """Return plaintext Telegram bot token (decrypts at-rest ciphertext)."""
    credentials = _credentials_dict(bot)
    stored = credentials.get("telegram_bot_token")
    if not stored:
        stored = _telegram_channel(credentials).get("telegram_bot_token")
    if not stored or not isinstance(stored, str):
        raise ValueError("Telegram bot token is missing from credentials")
    try:
        return decrypt_credential(stored)
    except Exception as exc:
        logger.warning(
            "BotCredentials.telegram_token_fallback | bot_id={bot_id} error={error}",
            bot_id=getattr(bot, "id", None),
            error=str(exc),
        )
        # Graceful fallback for old unencrypted test rows.
        return stored


def set_telegram_bot_token(bot: BotModel, token: str) -> None:
    """Persist Telegram bot token as AES-encrypted ciphertext in credentials JSON."""
    plain = token.strip()
    sealed = encrypt_credential(plain)
    credentials = _credentials_dict(bot)
    credentials["telegram_bot_token"] = sealed

    channels = credentials.get("channels")
    if not isinstance(channels, dict):
        channels = {}
    telegram = dict(channels.get("telegram") or {})
    telegram["telegram_bot_token"] = sealed
    channels["telegram"] = telegram
    credentials["channels"] = channels
    bot.credentials = credentials


def get_channel_access_token(bot: BotModel, channel: str, field_name: str) -> str | None:
    """Decrypt a nested channel access token (WhatsApp / Instagram / VK)."""
    credentials = _credentials_dict(bot)
    stored = credentials.get(field_name)
    if not stored:
        channels = credentials.get("channels") if isinstance(credentials.get("channels"), dict) else {}
        channel_cfg = channels.get(channel) if isinstance(channels.get(channel), dict) else {}
        stored = channel_cfg.get(field_name)
    if not stored or not isinstance(stored, str):
        return None
    try:
        return decrypt_credential(stored)
    except Exception as exc:
        logger.warning(
            "BotCredentials.channel_token_fallback | channel={channel} error={error}",
            channel=channel,
            error=str(exc),
        )
        return stored


class _TelegramBotTokenDescriptor:
    """Instance attribute wrapper: read decrypts, write encrypts."""

    def __get__(self, obj: BotModel | None, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return get_telegram_bot_token(obj)

    def __set__(self, obj: BotModel, value: str) -> None:
        set_telegram_bot_token(obj, value)


def _attach_credential_descriptors() -> None:
    if getattr(BotModel, "_mpai_crypto_descriptors_attached", False):
        return
    BotModel.telegram_bot_token = _TelegramBotTokenDescriptor()  # type: ignore[attr-defined, assignment]
    BotModel._mpai_crypto_descriptors_attached = True  # type: ignore[attr-defined]


_attach_credential_descriptors()

# Public alias — importers can use ``from app.models.bot import Bot``.
Bot = BotModel

__all__ = [
    "Bot",
    "EncryptedString",
    "get_telegram_bot_token",
    "set_telegram_bot_token",
    "get_channel_access_token",
]
