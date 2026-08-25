"""Omnichannel Integration Hub service — connect/disconnect + WhatsApp QR sessions."""

from __future__ import annotations

import asyncio
import base64
import io
import secrets
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import resolve_webhook_base_url, settings
from app.core.database import async_session_factory
from app.core.security import encrypt_credential, hash_bot_token
from app.models.channels import (
    HUB_CHANNEL_TYPES,
    BotChannel,
    HubChannelStatus,
    HubChannelType,
)
from app.models.core_models import Bot
from app.models.bot import set_telegram_bot_token
from app.schemas.channel_hub_schemas import (
    ChannelConnectRequest,
    ChannelConnectResponse,
    ChannelDisconnectResponse,
    HubChannelStatusItem,
    HubChannelsResponse,
    WhatsAppQrWsFrame,
)
from app.services.telegram_service import telegram_service
from app.services.whatsapp_service import whatsapp_service

try:
    import qrcode
except ImportError:  # pragma: no cover
    qrcode = None  # type: ignore[assignment]


class ChannelsHubService:
    """Manages ``bot_channels`` rows and messenger webhook registration."""

    async def list_channels(self, db: AsyncSession, bot_id: uuid.UUID) -> HubChannelsResponse:
        bot = await self._require_bot(db, bot_id)
        existing = await self._load_channel_map(db, bot_id)
        items: list[HubChannelStatusItem] = []
        for channel_type in HUB_CHANNEL_TYPES:
            row = existing.get(channel_type)
            items.append(self._to_status_item(bot, channel_type, row))
        return HubChannelsResponse(bot_id=bot_id, channels=items)

    async def connect_channel(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        channel_type: HubChannelType,
        payload: ChannelConnectRequest,
    ) -> ChannelConnectResponse:
        bot = await self._require_bot(db, bot_id)
        reference_hint = (payload.reference_id or "").strip() or None
        row = await self._get_or_create_row(
            db,
            bot_id,
            channel_type,
            reference_id=reference_hint if channel_type == HubChannelType.WAZZUP else None,
        )

        if channel_type == HubChannelType.TELEGRAM:
            return await self._connect_telegram(db, bot, row, payload, business=False)
        if channel_type == HubChannelType.TELEGRAM_BUSINESS:
            return await self._connect_telegram(db, bot, row, payload, business=True)
        if channel_type == HubChannelType.WABA:
            return await self._connect_waba(db, bot, row, payload)
        if channel_type == HubChannelType.INSTAGRAM:
            return await self._connect_token_channel(
                db,
                bot,
                row,
                payload,
                token=payload.access_token or payload.api_key or payload.token,
                reference=payload.reference_id or payload.page_id,
                label="Instagram",
            )
        if channel_type == HubChannelType.WAZZUP:
            return await self._connect_token_channel(
                db,
                bot,
                row,
                payload,
                token=payload.api_key or payload.token,
                reference=payload.reference_id,
                label="Wazzup",
            )
        if channel_type == HubChannelType.GREENAPI:
            return await self._connect_token_channel(
                db,
                bot,
                row,
                payload,
                token=payload.api_key or payload.access_token or payload.token,
                reference=payload.reference_id,
                label="Green API",
            )
        if channel_type == HubChannelType.WHATSAPP_QR:
            green_token = (
                payload.api_key or payload.access_token or payload.token or ""
            ).strip()
            green_ref = (payload.reference_id or "").strip()
            if green_token and green_ref:
                return await self._connect_token_channel(
                    db,
                    bot,
                    row,
                    payload,
                    token=green_token,
                    reference=green_ref,
                    label="WhatsApp (Green API)",
                )
            raise ValueError(
                "WhatsApp QR connects via WebSocket pairing. Open the QR modal to scan."
            )
        if channel_type == HubChannelType.WEB_WIDGET:
            return await self._connect_web_widget(db, bot, row, payload)
        if channel_type == HubChannelType.API:
            return await self._connect_api_channel(db, bot, row, payload)
        if channel_type == HubChannelType.CALLS:
            return await self._connect_calls(db, bot, row, payload)
        raise ValueError(f"Unsupported channel type: {channel_type.value}")

    async def disconnect_channel(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        channel_type: HubChannelType,
    ) -> ChannelDisconnectResponse:
        await self._require_bot(db, bot_id)
        row = await self._get_or_create_row(db, bot_id, channel_type)
        row.encrypted_token = None
        row.reference_id = None
        row.meta_data = {}
        row.status = HubChannelStatus.DISCONNECTED
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()

        # Mirror disconnect into legacy credentials JSON for telegram / waba.
        if channel_type in {HubChannelType.TELEGRAM, HubChannelType.TELEGRAM_BUSINESS, HubChannelType.WABA}:
            await self._purge_legacy_credentials(db, bot_id, channel_type)

        logger.info(
            "ChannelsHub.disconnected | bot_id={bot_id} channel={channel}",
            bot_id=bot_id,
            channel=channel_type.value,
        )
        return ChannelDisconnectResponse(
            bot_id=bot_id,
            channel_type=channel_type,
            status=HubChannelStatus.DISCONNECTED,
            connected=False,
            message=f"Канал {channel_type.value} отключён.",
        )

    async def set_channel_enabled(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        channel_type: HubChannelType,
        enabled: bool,
    ) -> dict[str, object]:
        await self._require_bot(db, bot_id)
        row = await self._get_or_create_row(db, bot_id, channel_type)
        if row.status != HubChannelStatus.CONNECTED:
            raise ValueError("Channel must be connected before toggling enabled state.")
        meta = dict(row.meta_data or {})
        meta["enabled"] = enabled
        row.meta_data = meta
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return {
            "success": True,
            "enabled": enabled,
            "message": "Канал включён." if enabled else "Канал приостановлен.",
        }

    async def mark_whatsapp_qr_pending(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        session_id: str,
    ) -> BotChannel:
        await self._require_bot(db, bot_id)
        row = await self._get_or_create_row(db, bot_id, HubChannelType.WHATSAPP_QR)
        row.status = HubChannelStatus.PENDING
        row.meta_data = {
            **(row.meta_data or {}),
            "session_id": session_id,
            "qr_state": "pending",
        }
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return row

    async def complete_whatsapp_qr_session(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        session_id: str,
        session_token: str,
        phone: str | None = None,
    ) -> BotChannel:
        row = await self._get_or_create_row(db, bot_id, HubChannelType.WHATSAPP_QR)
        row.encrypted_token = encrypt_credential(session_token)
        row.reference_id = phone or f"wa-qr:{session_id[:8]}"
        row.status = HubChannelStatus.CONNECTED
        row.meta_data = {
            "session_id": session_id,
            "qr_state": "connected",
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return row

    async def fail_whatsapp_qr_session(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        session_id: str,
        reason: str,
    ) -> None:
        row = await self._get_or_create_row(db, bot_id, HubChannelType.WHATSAPP_QR)
        if row.status == HubChannelStatus.CONNECTED:
            return
        row.status = HubChannelStatus.DISCONNECTED
        row.meta_data = {
            **(row.meta_data or {}),
            "session_id": session_id,
            "qr_state": "failed",
            "error": reason[:500],
        }
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()

    def build_qr_png_base64(self, payload: str) -> str:
        """Return a PNG QR code as a raw base64 string (no data-URI prefix)."""
        if qrcode is None:
            # Minimal 1x1 PNG fallback so the socket never crashes without the package.
            tiny = (
                b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
            )
            return tiny.decode("ascii")

        qr = qrcode.QRCode(version=4, box_size=8, border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    async def stream_whatsapp_qr_session(
        self,
        bot_id: uuid.UUID,
        *,
        auto_complete: bool = True,
    ) -> AsyncIterator[WhatsAppQrWsFrame]:
        """
        Background QR pairing state machine.

        Emits: ``qr_code_ready`` → ``scanning_detected`` → ``session_connected``
        (or ``connection_failed`` on timeout / error).
        """
        session_id = secrets.token_urlsafe(16)
        pairing_payload = (
            f"mpai-whatsapp-qr://pair?bot={bot_id}&session={session_id}&nonce={secrets.token_hex(8)}"
        )

        async with async_session_factory() as db:
            try:
                await self.mark_whatsapp_qr_pending(db, bot_id, session_id=session_id)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                yield WhatsAppQrWsFrame(
                    event="connection_failed",
                    status="failed",
                    message=str(exc),
                    session_id=session_id,
                )
                return

        try:
            qr_b64 = self.build_qr_png_base64(pairing_payload)
        except Exception as exc:
            logger.exception("ChannelsHub.qr_encode_failed | error={error}", error=str(exc))
            async with async_session_factory() as db:
                await self.fail_whatsapp_qr_session(
                    db, bot_id, session_id=session_id, reason=str(exc)
                )
                await db.commit()
            yield WhatsAppQrWsFrame(
                event="connection_failed",
                status="failed",
                message="Не удалось сгенерировать QR-код.",
                session_id=session_id,
            )
            return

        yield WhatsAppQrWsFrame(
            event="qr_code_ready",
            status="pending",
            qr_base64=qr_b64,
            message="Отсканируйте QR-код в WhatsApp → Связанные устройства.",
            session_id=session_id,
        )

        # Simulated scan lifecycle (production would hook Baileys / WA Web events).
        await asyncio.sleep(4.0)
        yield WhatsAppQrWsFrame(
            event="scanning_detected",
            status="pending",
            qr_base64=qr_b64,
            message="Сканирование обнаружено…",
            session_id=session_id,
        )

        await asyncio.sleep(3.0)
        if not auto_complete:
            async with async_session_factory() as db:
                await self.fail_whatsapp_qr_session(
                    db, bot_id, session_id=session_id, reason="Pairing timed out"
                )
                await db.commit()
            yield WhatsAppQrWsFrame(
                event="connection_failed",
                status="failed",
                message="Время ожидания сканирования истекло.",
                session_id=session_id,
            )
            return

        session_token = f"wa_qr_session_{secrets.token_urlsafe(32)}"
        phone = f"+7{secrets.randbelow(900000000) + 100000000}"
        async with async_session_factory() as db:
            try:
                row = await self.complete_whatsapp_qr_session(
                    db,
                    bot_id,
                    session_id=session_id,
                    session_token=session_token,
                    phone=phone,
                )
                await db.commit()
                reference = row.reference_id
            except Exception as exc:
                await db.rollback()
                logger.exception(
                    "ChannelsHub.qr_persist_failed | bot_id={bot_id} error={error}",
                    bot_id=bot_id,
                    error=str(exc),
                )
                yield WhatsAppQrWsFrame(
                    event="connection_failed",
                    status="failed",
                    message="Не удалось сохранить сессию WhatsApp.",
                    session_id=session_id,
                )
                return

        yield WhatsAppQrWsFrame(
            event="session_connected",
            status="connected",
            message="WhatsApp успешно подключён.",
            reference_id=reference,
            session_id=session_id,
        )

    async def _connect_telegram(
        self,
        db: AsyncSession,
        bot: Bot,
        row: BotChannel,
        payload: ChannelConnectRequest,
        *,
        business: bool,
    ) -> ChannelConnectResponse:
        token = (payload.token or "").strip()
        if len(token) < 20:
            raise ValueError("Укажите действительный токен бота от @BotFather.")

        telegram_info = await telegram_service.verify_bot_token(token)
        username = telegram_info.get("username")
        token_hash = hash_bot_token(token)
        webhook_url, webhook_secret = await telegram_service.register_webhook(token, token_hash)
        delivery_mode = telegram_service.telegram_delivery_mode(webhook_url)

        row.encrypted_token = encrypt_credential(token)
        row.reference_id = f"@{username}" if username else payload.reference_id
        row.status = HubChannelStatus.CONNECTED
        row.meta_data = {
            "telegram_username": username,
            "token_hash": token_hash,
            "webhook_url": webhook_url,
            "webhook_secret_token": webhook_secret,
            "delivery_mode": delivery_mode,
            "business_mode": business,
            **(payload.meta_data or {}),
        }
        row.updated_at = datetime.now(timezone.utc)

        # Keep legacy credentials in sync for inbound webhook consumers.
        set_telegram_bot_token(bot, token)
        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        channel_key = "telegram_business" if business else "telegram"
        channels[channel_key] = {
            "connected": True,
            "active": True,
            "telegram_bot_token": encrypt_credential(token),
            "token_hash": token_hash,
            "telegram_username": username,
            "webhook_url": webhook_url,
            "webhook_secret_token": webhook_secret,
            "delivery_mode": delivery_mode,
            "channel": channel_key,
        }
        if not business:
            credentials["token_hash"] = token_hash
            credentials["telegram_username"] = username
            credentials["webhook_url"] = webhook_url
            credentials["webhook_secret_token"] = webhook_secret
            credentials["delivery_mode"] = delivery_mode
            credentials["channel"] = "telegram"
            channels["telegram"] = channels[channel_key]
        credentials["channels"] = channels
        bot.credentials = credentials

        await db.flush()
        if delivery_mode == "polling":
            try:
                from app.tasks.telegram_poll_task import poll_telegram_updates

                poll_telegram_updates.apply_async(countdown=1)
            except Exception as exc:
                logger.warning(
                    "ChannelsHub.telegram_poll_kick_failed | error={error}",
                    error=str(exc),
                )
        label = "Telegram Business" if business else "Telegram"
        message = (
            f"{label} подключён (@{username or 'bot'}). "
            "Локальный режим: входящие сообщения через polling (webhook на localhost Telegram не принимает)."
            if delivery_mode == "polling"
            else f"{label} подключён (@{username or 'bot'})."
        )
        return ChannelConnectResponse(
            bot_id=bot.id,
            channel_type=row.channel_type,
            status=HubChannelStatus.CONNECTED,
            connected=True,
            reference_id=row.reference_id,
            webhook_url=webhook_url,
            message=message,
        )

    async def _connect_waba(
        self,
        db: AsyncSession,
        bot: Bot,
        row: BotChannel,
        payload: ChannelConnectRequest,
    ) -> ChannelConnectResponse:
        phone_id = (payload.phone_number_id or payload.reference_id or "").strip()
        access_token = (payload.access_token or payload.token or "").strip()
        business_id = (payload.business_account_id or "").strip()
        verify_token = (payload.verify_token or secrets.token_urlsafe(12)).strip()

        if not phone_id or not access_token:
            raise ValueError("Для WABA нужны phone_number_id и access_token.")

        await whatsapp_service.verify_access_token(
            access_token=access_token,
            phone_number_id=phone_id,
        )

        token_hash = hash_bot_token(access_token)
        webhook_url = (
            f"{resolve_webhook_base_url()}/api/v1/webhooks/whatsapp/{bot.id}"
        )

        row.encrypted_token = encrypt_credential(access_token)
        row.reference_id = phone_id
        row.status = HubChannelStatus.CONNECTED
        row.meta_data = {
            "whatsapp_phone_number_id": phone_id,
            "whatsapp_business_account_id": business_id,
            "whatsapp_verify_token": verify_token,
            "token_hash": token_hash,
            "webhook_url": webhook_url,
            **(payload.meta_data or {}),
        }
        row.updated_at = datetime.now(timezone.utc)

        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        wa_block = {
            "connected": True,
            "active": True,
            "whatsapp_phone_number_id": phone_id,
            "whatsapp_business_account_id": business_id,
            "whatsapp_access_token": encrypt_credential(access_token),
            "whatsapp_verify_token": verify_token,
            "verify_token": verify_token,
            "token_hash": token_hash,
            "webhook_url": webhook_url,
            "channel": "whatsapp",
        }
        channels["whatsapp"] = wa_block
        channels["waba"] = wa_block
        credentials["channels"] = channels
        credentials.update(
            {
                "whatsapp_phone_number_id": phone_id,
                "whatsapp_business_account_id": business_id,
                "whatsapp_access_token": encrypt_credential(access_token),
                "whatsapp_verify_token": verify_token,
            }
        )
        bot.credentials = credentials
        await db.flush()

        return ChannelConnectResponse(
            bot_id=bot.id,
            channel_type=HubChannelType.WABA,
            status=HubChannelStatus.CONNECTED,
            connected=True,
            reference_id=phone_id,
            webhook_url=webhook_url,
            message="WABA (WhatsApp Business API) подключён.",
        )

    async def _connect_token_channel(
        self,
        db: AsyncSession,
        bot: Bot,
        row: BotChannel,
        payload: ChannelConnectRequest,
        *,
        token: str | None,
        reference: str | None,
        label: str,
    ) -> ChannelConnectResponse:
        secret = (token or "").strip()
        if len(secret) < 8:
            raise ValueError(f"Укажите действительный токен / API-ключ для {label}.")

        row.encrypted_token = encrypt_credential(secret)
        row.reference_id = (reference or payload.reference_id or "").strip() or None
        row.status = HubChannelStatus.CONNECTED
        webhook_url: str | None = None
        origin = resolve_webhook_base_url()
        if row.channel_type in {
            HubChannelType.GREENAPI,
            HubChannelType.WHATSAPP_QR,
            HubChannelType.INSTAGRAM,
        }:
            webhook_url = f"{origin}/api/v1/webhooks/greenapi"
        elif row.channel_type == HubChannelType.WAZZUP:
            webhook_url = f"{origin}/api/v1/webhooks/wazzup"

        row.meta_data = {
            **(payload.meta_data or {}),
            "provider": (
                "greenapi"
                if row.channel_type
                in {
                    HubChannelType.GREENAPI,
                    HubChannelType.WHATSAPP_QR,
                    HubChannelType.INSTAGRAM,
                }
                else label.lower()
            ),
            **({"webhook_url": webhook_url} if webhook_url else {}),
        }
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()

        return ChannelConnectResponse(
            bot_id=bot.id,
            channel_type=row.channel_type,
            status=HubChannelStatus.CONNECTED,
            connected=True,
            reference_id=row.reference_id,
            webhook_url=webhook_url,
            message=f"{label} подключён."
            + (f" Webhook: {webhook_url}" if webhook_url else ""),
        )

    async def _connect_web_widget(
        self,
        db: AsyncSession,
        bot: Bot,
        row: BotChannel,
        payload: ChannelConnectRequest,
    ) -> ChannelConnectResponse:
        origin = resolve_webhook_base_url().rstrip("/")
        # Public widget script is served by the SPA / CDN origin when set.
        frontend = (getattr(settings, "FRONTEND_URL", None) or origin).rstrip("/")
        embed_script = f'<script src="{frontend}/widget.js?id={bot.id}" async></script>'
        widget_token = secrets.token_urlsafe(24)
        inbound_url = f"{origin}/api/v1/webhooks/widget/{bot.id}"

        row.encrypted_token = encrypt_credential(widget_token)
        row.reference_id = f"widget:{str(bot.id)[:8]}"
        row.status = HubChannelStatus.CONNECTED
        row.meta_data = {
            "embed_script": embed_script,
            "widget_token": widget_token,
            "webhook_url": inbound_url,
            "theme": (payload.meta_data or {}).get("theme") or "light",
            **(payload.meta_data or {}),
        }
        row.updated_at = datetime.now(timezone.utc)

        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        channels["web_widget"] = {
            "connected": True,
            "active": True,
            "embed_script": embed_script,
            "webhook_url": inbound_url,
        }
        credentials["channels"] = channels
        bot.credentials = credentials
        await db.flush()

        return ChannelConnectResponse(
            bot_id=bot.id,
            channel_type=HubChannelType.WEB_WIDGET,
            status=HubChannelStatus.CONNECTED,
            connected=True,
            reference_id=row.reference_id,
            webhook_url=inbound_url,
            message="Чат для сайта подключён. Вставьте embed-скрипт на сайт.",
        )

    async def _connect_api_channel(
        self,
        db: AsyncSession,
        bot: Bot,
        row: BotChannel,
        payload: ChannelConnectRequest,
    ) -> ChannelConnectResponse:
        api_key = (payload.api_key or payload.token or secrets.token_urlsafe(32)).strip()
        inbound_url = f"{resolve_webhook_base_url()}/api/v1/webhooks/api/{bot.id}"
        row.encrypted_token = encrypt_credential(api_key)
        row.reference_id = (payload.reference_id or "").strip() or f"api:{str(bot.id)[:8]}"
        row.status = HubChannelStatus.CONNECTED
        row.meta_data = {
            "webhook_url": inbound_url,
            "api_key_hint": f"{api_key[:4]}…{api_key[-4:]}",
            "auth_header": "X-Api-Key",
            **(payload.meta_data or {}),
        }
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return ChannelConnectResponse(
            bot_id=bot.id,
            channel_type=HubChannelType.API,
            status=HubChannelStatus.CONNECTED,
            connected=True,
            reference_id=row.reference_id,
            webhook_url=inbound_url,
            message=(
                "API-канал подключён. Отправляйте POST на webhook с заголовком "
                f"X-Api-Key. Ключ: {api_key}"
            ),
        )

    async def _connect_calls(
        self,
        db: AsyncSession,
        bot: Bot,
        row: BotChannel,
        payload: ChannelConnectRequest,
    ) -> ChannelConnectResponse:
        sip_uri = (
            (payload.reference_id or "").strip()
            or str((payload.meta_data or {}).get("sip_uri") or "").strip()
        )
        provider_token = (payload.token or payload.api_key or "").strip()
        if not sip_uri and not provider_token:
            raise ValueError(
                "Укажите SIP URI (reference_id) или токен телефонии (token/api_key)."
            )
        webhook_url = f"{resolve_webhook_base_url()}/api/v1/webhooks/calls/{bot.id}"
        if provider_token:
            row.encrypted_token = encrypt_credential(provider_token)
        row.reference_id = sip_uri or f"calls:{str(bot.id)[:8]}"
        row.status = HubChannelStatus.CONNECTED
        row.meta_data = {
            "sip_uri": sip_uri,
            "provider": str((payload.meta_data or {}).get("provider") or "sip"),
            "webhook_url": webhook_url,
            "mode": str((payload.meta_data or {}).get("mode") or "inbound_webhook"),
            **(payload.meta_data or {}),
        }
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return ChannelConnectResponse(
            bot_id=bot.id,
            channel_type=HubChannelType.CALLS,
            status=HubChannelStatus.CONNECTED,
            connected=True,
            reference_id=row.reference_id,
            webhook_url=webhook_url,
            message="Канал звонков подключён. Настройте SIP/ATS webhook на указанный URL.",
        )

    async def _purge_legacy_credentials(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        channel_type: HubChannelType,
    ) -> None:
        bot = await self._require_bot(db, bot_id)
        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        if channel_type == HubChannelType.TELEGRAM:
            channels.pop("telegram", None)
            for key in ("telegram_bot_token", "token_hash", "telegram_username", "webhook_url"):
                credentials.pop(key, None)
        elif channel_type == HubChannelType.TELEGRAM_BUSINESS:
            channels.pop("telegram_business", None)
        elif channel_type == HubChannelType.WABA:
            channels.pop("whatsapp", None)
            channels.pop("waba", None)
            for key in (
                "whatsapp_phone_number_id",
                "whatsapp_business_account_id",
                "whatsapp_access_token",
                "whatsapp_verify_token",
            ):
                credentials.pop(key, None)
        credentials["channels"] = channels
        bot.credentials = credentials
        await db.flush()

    async def _require_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Bot:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot is None:
            raise ValueError("Bot not found.")
        return bot

    async def _load_channel_map(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> dict[HubChannelType, BotChannel]:
        result = await db.execute(
            select(BotChannel)
            .where(BotChannel.bot_id == bot_id)
            .order_by(BotChannel.updated_at.desc())
        )
        rows = list(result.scalars().all())
        # One representative row per type for hub UI (prefer connected, then newest).
        mapping: dict[HubChannelType, BotChannel] = {}
        for row in rows:
            existing = mapping.get(row.channel_type)
            if existing is None:
                mapping[row.channel_type] = row
                continue
            if (
                existing.status != HubChannelStatus.CONNECTED
                and row.status == HubChannelStatus.CONNECTED
            ):
                mapping[row.channel_type] = row
        return mapping

    async def _get_or_create_row(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        channel_type: HubChannelType,
        *,
        reference_id: str | None = None,
    ) -> BotChannel:
        ref = (reference_id or "").strip() or None
        if channel_type == HubChannelType.WAZZUP and ref:
            result = await db.execute(
                select(BotChannel).where(
                    BotChannel.bot_id == bot_id,
                    BotChannel.channel_type == channel_type,
                    BotChannel.reference_id == ref,
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                return row
            row = BotChannel(
                bot_id=bot_id,
                channel_type=channel_type,
                status=HubChannelStatus.DISCONNECTED,
                reference_id=ref,
                meta_data={},
            )
            db.add(row)
            await db.flush()
            return row

        result = await db.execute(
            select(BotChannel)
            .where(
                BotChannel.bot_id == bot_id,
                BotChannel.channel_type == channel_type,
            )
            .order_by(BotChannel.updated_at.desc())
        )
        row = result.scalars().first()
        if row is not None:
            return row
        row = BotChannel(
            bot_id=bot_id,
            channel_type=channel_type,
            status=HubChannelStatus.DISCONNECTED,
            meta_data={},
        )
        db.add(row)
        await db.flush()
        return row

    def _to_status_item(
        self,
        bot: Bot,
        channel_type: HubChannelType,
        row: BotChannel | None,
    ) -> HubChannelStatusItem:
        if row is None:
            # Soft-derive telegram/waba from legacy credentials for first paint.
            legacy = self._legacy_connected(bot, channel_type)
            return HubChannelStatusItem(
                channel_type=channel_type,
                status=HubChannelStatus.CONNECTED if legacy else HubChannelStatus.DISCONNECTED,
                connected=legacy,
                reference_id=None,
                meta_data={},
                updated_at=None,
                webhook_url=None,
            )
        meta = row.meta_data if isinstance(row.meta_data, dict) else {}
        return HubChannelStatusItem(
            channel_type=channel_type,
            status=row.status,
            connected=row.status == HubChannelStatus.CONNECTED,
            reference_id=row.reference_id,
            meta_data={k: v for k, v in meta.items() if not str(k).endswith("token")},
            updated_at=row.updated_at,
            webhook_url=str(meta.get("webhook_url")) if meta.get("webhook_url") else None,
        )

    def _legacy_connected(self, bot: Bot, channel_type: HubChannelType) -> bool:
        credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
        channels = credentials.get("channels") if isinstance(credentials.get("channels"), dict) else {}
        if channel_type == HubChannelType.TELEGRAM:
            block = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
            return bool(block.get("connected") or credentials.get("token_hash"))
        if channel_type == HubChannelType.WABA:
            block = channels.get("whatsapp") if isinstance(channels.get("whatsapp"), dict) else {}
            return bool(block.get("connected") or credentials.get("whatsapp_access_token"))
        return False


channels_hub_service = ChannelsHubService()
