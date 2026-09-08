"""Bootstrap Telegram inbound delivery for every connected hub channel on API start."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import is_public_https_webhook_url, resolve_webhook_base_url, settings
from app.core.database import async_session_factory
from app.core.security import decrypt_credential, generate_webhook_secret, hash_bot_token
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.models.core_models import Bot


def _channel_path_secret(meta: dict[str, Any], bot_token: str) -> str:
    """Path segment for ``/webhooks/telegram/{token_hash}`` (never the BotFather token)."""
    stored = str(meta.get("token_hash") or "").strip()
    if stored:
        return stored
    return hash_bot_token(bot_token)


def _channel_header_secret(meta: dict[str, Any]) -> str:
    stored = str(
        meta.get("webhook_secret_token") or meta.get("telegram_webhook_secret") or ""
    ).strip()
    return stored or generate_webhook_secret()


async def _load_connected_telegram_channels(db: AsyncSession) -> list[BotChannel]:
    result = await db.execute(
        select(BotChannel).where(
            BotChannel.channel_type.in_(
                (HubChannelType.TELEGRAM, HubChannelType.TELEGRAM_BUSINESS)
            ),
            BotChannel.status == HubChannelStatus.CONNECTED,
            BotChannel.encrypted_token.is_not(None),
        )
    )
    return list(result.scalars().all())


async def _sync_bot_credentials_webhook(
    db: AsyncSession,
    *,
    bot_id: Any,
    channel_type: HubChannelType,
    path_secret: str,
    webhook_url: str,
    header_secret: str,
    delivery_mode: str,
) -> None:
    bot = await db.get(Bot, bot_id)
    if bot is None:
        return
    channel_key = (
        "telegram_business"
        if channel_type == HubChannelType.TELEGRAM_BUSINESS
        else "telegram"
    )
    credentials = dict(bot.credentials or {}) if isinstance(bot.credentials, dict) else {}
    channels = (
        dict(credentials.get("channels") or {})
        if isinstance(credentials.get("channels"), dict)
        else {}
    )
    telegram_block = (
        dict(channels.get(channel_key) or {})
        if isinstance(channels.get(channel_key), dict)
        else {}
    )
    telegram_block.update(
        {
            "connected": True,
            "active": True,
            "token_hash": path_secret,
            "webhook_url": webhook_url,
            "webhook_secret_token": header_secret,
            "delivery_mode": delivery_mode,
            "channel": channel_key,
        }
    )
    channels[channel_key] = telegram_block
    if channel_key == "telegram":
        credentials["token_hash"] = path_secret
        credentials["webhook_url"] = webhook_url
        credentials["webhook_secret_token"] = header_secret
        credentials["delivery_mode"] = delivery_mode
    credentials["channels"] = channels
    bot.credentials = credentials


def _arm_telegram_poller() -> None:
    try:
        from app.tasks.telegram_poll_task import poll_telegram_updates

        poll_telegram_updates.apply_async(countdown=1)
        logger.info("TelegramWebhookManager.poller_armed")
    except Exception as exc:
        logger.error(
            "TelegramWebhookManager.poller_arm_failed | error={error} "
            "hint=ensure celery_worker is running",
            error=str(exc),
        )


async def register_all_webhooks() -> dict[str, int]:
    """
    Ensure every connected Telegram channel has a working inbound path.

    - Public HTTPS base → ``setWebhook`` with ``token_hash`` path + header secret.
    - Non-public base (localhost) → clear Telegram webhook + ``delivery_mode=polling``
      and arm Celery ``getUpdates`` poller (webhook + getUpdates cannot coexist).
    """
    from app.services.telegram_service import telegram_service

    stats = {
        "total": 0,
        "registered": 0,
        "polling": 0,
        "skipped": 0,
        "failed": 0,
    }
    base = resolve_webhook_base_url()
    base_is_public = is_public_https_webhook_url(f"{base}/api/v1/webhooks/telegram/x")
    logger.info(
        "TelegramWebhookManager.bootstrap_start | base={base} public={public} "
        "env_webhook={env} ngrok_set={ngrok}",
        base=base,
        public=base_is_public,
        env=settings.WEBHOOK_BASE_URL,
        ngrok=bool(settings.NGROK_TUNNEL_URL),
    )
    if not base_is_public:
        logger.warning(
            "TelegramWebhookManager.non_public_base | "
            "using polling fallback — set WEBHOOK_BASE_URL or NGROK_TUNNEL_URL "
            "to public HTTPS before commercial deploy"
        )

    async with async_session_factory() as db:
        rows = await _load_connected_telegram_channels(db)
        stats["total"] = len(rows)

        for row in rows:
            meta = dict(row.meta_data) if isinstance(row.meta_data, dict) else {}
            try:
                bot_token = decrypt_credential(row.encrypted_token or "")
            except Exception as exc:
                stats["failed"] += 1
                # The token is sealed with a key we no longer hold, so this channel
                # can never deliver. Stop reporting it as connected — the UI has to
                # prompt for re-entry instead of showing a green channel that is dead.
                row.status = HubChannelStatus.DISCONNECTED
                meta["credential_error"] = "decrypt_failed"
                meta["credential_error_at"] = datetime.now(timezone.utc).isoformat()
                row.meta_data = meta
                logger.error(
                    "TelegramWebhookManager.decrypt_failed | bot_id={bot_id} "
                    "channel_id={channel_id} error={error} "
                    "action=channel marked disconnected, token must be re-entered",
                    bot_id=row.bot_id,
                    channel_id=row.id,
                    error=str(exc),
                )
                continue

            if not isinstance(bot_token, str) or not bot_token.strip():
                stats["skipped"] += 1
                logger.warning(
                    "TelegramWebhookManager.empty_token | bot_id={bot_id} channel_id={channel_id}",
                    bot_id=row.bot_id,
                    channel_id=row.id,
                )
                continue

            bot_token = bot_token.strip()
            path_secret = _channel_path_secret(meta, bot_token)
            header_secret = _channel_header_secret(meta)
            expected_url = f"{base}/api/v1/webhooks/telegram/{path_secret}"

            if not is_public_https_webhook_url(expected_url):
                # getUpdates only works when no webhook is registered on Telegram.
                try:
                    await telegram_service.delete_webhook(bot_token)
                except Exception as exc:
                    logger.warning(
                        "TelegramWebhookManager.delete_webhook_failed | bot_id={bot_id} "
                        "error={error}",
                        bot_id=row.bot_id,
                        error=str(exc),
                    )
                delivery_mode = "polling"
                meta.update(
                    {
                        "token_hash": path_secret,
                        "webhook_url": expected_url,
                        "webhook_secret_token": header_secret,
                        "delivery_mode": delivery_mode,
                        "webhook_synced_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                row.meta_data = meta
                row.updated_at = datetime.now(timezone.utc)
                await _sync_bot_credentials_webhook(
                    db,
                    bot_id=row.bot_id,
                    channel_type=row.channel_type,
                    path_secret=path_secret,
                    webhook_url=expected_url,
                    header_secret=header_secret,
                    delivery_mode=delivery_mode,
                )
                stats["polling"] += 1
                logger.info(
                    "TelegramWebhookManager.polling_enabled | bot_id={bot_id} "
                    "channel_id={channel_id}",
                    bot_id=row.bot_id,
                    channel_id=row.id,
                )
                continue

            try:
                webhook_url, secret = await telegram_service.register_webhook(
                    bot_token,
                    path_secret,
                    secret_token=header_secret,
                    on_non_public="raise",
                )
            except Exception as exc:
                stats["failed"] += 1
                logger.error(
                    "TelegramWebhookManager.set_webhook_failed | bot_id={bot_id} "
                    "channel_id={channel_id} url={url} error={error}",
                    bot_id=row.bot_id,
                    channel_id=row.id,
                    url=expected_url,
                    error=str(exc),
                )
                continue

            delivery_mode = "webhook"
            meta.update(
                {
                    "token_hash": path_secret,
                    "webhook_url": webhook_url,
                    "webhook_secret_token": secret,
                    "delivery_mode": delivery_mode,
                    "webhook_synced_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            row.meta_data = meta
            row.updated_at = datetime.now(timezone.utc)
            await _sync_bot_credentials_webhook(
                db,
                bot_id=row.bot_id,
                channel_type=row.channel_type,
                path_secret=path_secret,
                webhook_url=webhook_url,
                header_secret=secret,
                delivery_mode=delivery_mode,
            )
            stats["registered"] += 1
            logger.info(
                "TelegramWebhookManager.registered | bot_id={bot_id} "
                "channel_id={channel_id} url={url}",
                bot_id=row.bot_id,
                channel_id=row.id,
                url=webhook_url,
            )

        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error(
                "TelegramWebhookManager.commit_failed | error={error}",
                error=str(exc),
            )
            raise

    logger.info(
        "TelegramWebhookManager.bootstrap_done | total={total} registered={registered} "
        "polling={polling} skipped={skipped} failed={failed}",
        **stats,
    )

    if stats["polling"] > 0:
        _arm_telegram_poller()

    return stats
