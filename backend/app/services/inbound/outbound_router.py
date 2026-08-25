"""Route LLM replies back to the transport that received the inbound message."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.inbound_message import InboundChannel, NormalizedInboundMessage
from app.schemas.media_schemas import MediaAttachment


async def deliver_outbound(
    db: AsyncSession,
    *,
    normalized: NormalizedInboundMessage,
    reply_text: str,
    payload: dict[str, Any] | None = None,
    media_attachments: list[MediaAttachment] | list[Any] | None = None,
    buttons: list[Any] | None = None,
    client_id: uuid.UUID | None = None,
) -> None:
    """
    Send ``reply_text`` through the channel named in ``normalized.channel``.

    Each adapter owns its transport credentials; this router picks the right one.
    """
    if not reply_text or not reply_text.strip():
        return

    from app.services.channel_sender import ChannelSenderFactory

    hub_type = str((payload or {}).get("hub_channel_type") or normalized.metadata.get("hub_channel_type") or "")
    parts = ChannelSenderFactory.format_outbound(
        reply_text,
        channel=normalized.channel,
        hub_type=hub_type or str(normalized.metadata.get("provider") or ""),
    )
    if not parts:
        return

    channel = normalized.channel
    bot_id = normalized.bot_id
    user_id = normalized.channel_user_id
    payload = payload or {}

    logger.info(
        "OutboundRouter.deliver | channel={channel} bot_id={bot_id} user_id={user_id} len={length} parts={parts}",
        channel=channel.value,
        bot_id=bot_id,
        user_id=user_id[:32],
        length=len(reply_text),
        parts=len(parts),
    )

    for index, part in enumerate(parts):
        part_buttons = buttons if index == 0 else None
        part_media = media_attachments if index == 0 else None
        await _deliver_one(
            db,
            normalized=normalized,
            reply_text=part,
            payload=payload,
            media_attachments=part_media,
            buttons=part_buttons,
            client_id=client_id,
            telegram_parse_mode="MarkdownV2" if channel == InboundChannel.TELEGRAM else None,
        )


async def _deliver_one(
    db: AsyncSession,
    *,
    normalized: NormalizedInboundMessage,
    reply_text: str,
    payload: dict[str, Any],
    media_attachments: list[MediaAttachment] | list[Any] | None,
    buttons: list[Any] | None,
    client_id: uuid.UUID | None,
    telegram_parse_mode: str | None,
) -> None:
    channel = normalized.channel
    bot_id = normalized.bot_id
    user_id = normalized.channel_user_id
    payload = payload or {}

    if channel == InboundChannel.TELEGRAM:
        await _deliver_telegram(
            db,
            bot_id=bot_id,
            chat_id=user_id,
            reply=reply_text,
            payload=payload,
            media_attachments=media_attachments,
            buttons=buttons,
            client_id=client_id,
            parse_mode=telegram_parse_mode,
        )
        return

    if channel == InboundChannel.WHATSAPP:
        provider = str(normalized.metadata.get("provider") or payload.get("platform_type") or "").lower()
        if provider in {"wazzup", "wazzup24"}:
            await _deliver_wazzup(
                db,
                bot_id=bot_id,
                chat_id=user_id,
                reply=reply_text,
                payload=payload,
                normalized=normalized,
            )
        elif provider in {"whatsapp_qr", "baileys", "whatsapp-qr"}:
            await _deliver_whatsapp_qr(bot_id=bot_id, phone=user_id, reply=reply_text)
        else:
            await _deliver_whatsapp_cloud(
                db,
                bot_id=bot_id,
                phone=user_id,
                reply=reply_text,
                payload=payload,
                media_attachments=media_attachments,
            )
        return

    if channel == InboundChannel.WEB:
        hub_type = str(normalized.metadata.get("hub_channel_type") or "web_widget").lower()
        if hub_type == "api":
            await _deliver_api_callback(bot_id=bot_id, session_id=user_id, reply=reply_text, payload=payload)
            return
        if hub_type == "calls":
            await _deliver_calls_reply(bot_id=bot_id, session_id=user_id, reply=reply_text)
            return
        await _deliver_web_widget(bot_id=bot_id, session_id=user_id, reply=reply_text)
        return

    hub_type = str(normalized.metadata.get("hub_channel_type") or "").lower()
    if hub_type == "instagram":
        await _deliver_instagram(db, bot_id=bot_id, user_id=user_id, reply=reply_text, payload=payload)
        return

    logger.warning(
        "OutboundRouter.unsupported_channel | channel={channel} bot_id={bot_id}",
        channel=channel.value,
        bot_id=bot_id,
    )


async def _deliver_telegram(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    chat_id: str,
    reply: str,
    payload: dict[str, Any],
    media_attachments: list[Any] | None,
    buttons: list[Any] | None,
    client_id: uuid.UUID | None,
    parse_mode: str | None = None,
) -> None:
    from app.models.core_models import Bot
    from app.services.telegram_service import telegram_service

    bot = await db.get(Bot, bot_id)
    if bot is None:
        return
    try:
        token = telegram_service.extract_bot_token(bot)
    except ValueError:
        logger.error("OutboundRouter.telegram_no_token | bot_id={bot_id}", bot_id=bot_id)
        return

    await telegram_service.send_message(
        bot_token=token,
        chat_id=chat_id,
        text=reply,
        buttons=[b.model_dump() if hasattr(b, "model_dump") else b for b in (buttons or [])],
        bot_id=bot_id,
        client_id=client_id,
        db=db,
        parse_mode=parse_mode,
    )
    if media_attachments:
        from app.schemas.media_schemas import MediaAttachment as MA

        normalized = [
            item if isinstance(item, MA) else MA.model_validate(item)
            for item in media_attachments
        ]
        await telegram_service.dispatch_media_attachments(
            bot_token=token,
            chat_id=chat_id,
            attachments=normalized,
            bot_id=bot_id,
            client_id=client_id,
            db=db,
        )


async def _deliver_whatsapp_cloud(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    phone: str,
    reply: str,
    payload: dict[str, Any],
    media_attachments: list[Any] | None,
) -> None:
    from app.core.security import decrypt_credential
    from app.models.core_models import Bot
    from app.services.whatsapp_service import whatsapp_service

    bot = await db.get(Bot, bot_id)
    if bot is None:
        return
    credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
    access_token_enc = credentials.get("whatsapp_access_token") or credentials.get("access_token")
    phone_number_id = credentials.get("phone_number_id") or credentials.get("whatsapp_phone_number_id")
    channels = credentials.get("channels") if isinstance(credentials.get("channels"), dict) else {}
    wa = channels.get("whatsapp") if isinstance(channels.get("whatsapp"), dict) else {}
    if not access_token_enc:
        access_token_enc = wa.get("access_token")
    if not phone_number_id:
        phone_number_id = wa.get("phone_number_id")
    if not access_token_enc or not phone_number_id:
        logger.warning("OutboundRouter.whatsapp_cloud_no_credentials | bot_id={bot_id}", bot_id=bot_id)
        return
    token = decrypt_credential(str(access_token_enc))
    await whatsapp_service.send_text_message(
        access_token=token,
        phone_number_id=str(phone_number_id),
        recipient=phone,
        text=reply,
        bot_id=bot_id,
        db=db,
    )


async def _deliver_wazzup(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    chat_id: str,
    reply: str,
    payload: dict[str, Any],
    normalized: NormalizedInboundMessage | None = None,
) -> None:
    from app.services.wazzup_service import wazzup_service

    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    meta = normalized.metadata if normalized is not None else {}
    inbound_payload = payload.get("inbound_payload") if isinstance(payload.get("inbound_payload"), dict) else {}
    channel_id = str(
        meta.get("channel_id")
        or inbound_payload.get("channel_id")
        or payload.get("channel_id")
        or body.get("channelId")
        or body.get("channel_id")
        or ""
    ).strip()

    channel = await wazzup_service.get_channel(db, bot_id, channel_id=channel_id or None)
    if channel is None:
        return
    api_key = wazzup_service.resolve_api_key(channel)
    if not api_key:
        return
    await wazzup_service.send_text_message(
        api_key=api_key,
        chat_id=chat_id,
        channel_id=channel_id or str(channel.reference_id or ""),
        text=reply,
    )


async def _deliver_whatsapp_qr(*, bot_id: uuid.UUID, phone: str, reply: str) -> None:
    from app.services.whatsapp_qr_service import whatsapp_qr_service

    await whatsapp_qr_service.send_text_message(bot_id=bot_id, to=phone, text=reply)


async def _deliver_web_widget(*, bot_id: uuid.UUID, session_id: str, reply: str) -> None:
    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    key = f"widget:reply:{bot_id}:{session_id}"
    client.lpush(key, reply)
    client.expire(key, 3600)


async def _deliver_api_callback(
    *,
    bot_id: uuid.UUID,
    session_id: str,
    reply: str,
    payload: dict[str, Any],
) -> None:
    import httpx

    callback_url = str(payload.get("callback_url") or payload.get("reply_url") or "").strip()
    if not callback_url:
        logger.warning("OutboundRouter.api_no_callback | bot_id={bot_id}", bot_id=bot_id)
        return
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(callback_url, json={"bot_id": str(bot_id), "user_id": session_id, "text": reply})


async def _deliver_calls_reply(*, bot_id: uuid.UUID, session_id: str, reply: str) -> None:
    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    key = f"calls:reply:{bot_id}:{session_id}"
    client.lpush(key, reply)
    client.expire(key, 3600)


async def _deliver_instagram(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    user_id: str,
    reply: str,
    payload: dict[str, Any],
) -> None:
    from app.core.security import decrypt_credential
    from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
    from app.services.instagram_service import instagram_service
    from sqlalchemy import select

    result = await db.execute(
        select(BotChannel).where(
            BotChannel.bot_id == bot_id,
            BotChannel.channel_type == HubChannelType.INSTAGRAM,
            BotChannel.status == HubChannelStatus.CONNECTED,
        )
    )
    row = result.scalar_one_or_none()
    if row is None or not row.encrypted_token:
        logger.warning("OutboundRouter.instagram_no_credentials | bot_id={bot_id}", bot_id=bot_id)
        return
    token = decrypt_credential(row.encrypted_token)
    await instagram_service.send_text_message(
        access_token=token,
        recipient_id=user_id,
        text=reply,
    )


async def resolve_client_outbound(
    db: AsyncSession,
    *,
    client: Any,
    bot: Any,
) -> NormalizedInboundMessage:
    """Build routing DTO for operator panel outbound based on client history + bot channels."""
    from sqlalchemy import select

    from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
    from app.models.core_models import MessageSender, PlatformType
    from app.services.inbound.normalizer import normalize_telegram, normalize_web_widget, normalize_whatsapp
    from app.utils.phone_utils import clean_phone_number

    latest_payload: dict[str, Any] = {}
    loaded_messages = list(getattr(client, "messages", []) or [])
    if loaded_messages:
        for message in reversed(loaded_messages):
            if message.sender == MessageSender.CLIENT:
                latest_payload = message.payload if isinstance(message.payload, dict) else {}
                break
    else:
        from app.models.core_models import ChatMessage

        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.client_id == client.id,
                ChatMessage.sender == MessageSender.CLIENT,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest is not None:
            latest_payload = latest.payload if isinstance(latest.payload, dict) else {}

    source = str(latest_payload.get("source") or latest_payload.get("channel") or "").lower()
    nested = latest_payload.get("inbound_payload")
    nested_payload = nested if isinstance(nested, dict) else {}
    provider = str(
        latest_payload.get("provider") or nested_payload.get("provider") or ""
    ).lower()

    if source in {"web_widget", "web"} or bot.platform_type == PlatformType.WEB_WIDGET:
        return normalize_web_widget(
            bot_id=bot.id,
            session_id=client.external_id,
            message_text="",
            username=client.username or client.first_name or client.external_id,
            raw_payload={"operator_outbound": True},
        )

    whatsapp_like = (
        source in {"wazzup", "whatsapp_qr", "whatsapp", "whatsapp_cloud"}
        or provider in {"wazzup", "whatsapp_qr", "whatsapp"}
        or bot.platform_type == PlatformType.WHATSAPP
    )
    if whatsapp_like:
        connected: list[BotChannel] = []
        if not provider:
            channel_result = await db.execute(
                select(BotChannel).where(
                    BotChannel.bot_id == bot.id,
                    BotChannel.status == HubChannelStatus.CONNECTED,
                    BotChannel.channel_type.in_(
                        [
                            HubChannelType.WAZZUP,
                            HubChannelType.WHATSAPP_QR,
                            HubChannelType.WABA,
                        ]
                    ),
                )
            )
            connected = list(channel_result.scalars().all())
            if any(row.channel_type == HubChannelType.WAZZUP for row in connected):
                provider = "wazzup"
            elif any(row.channel_type == HubChannelType.WHATSAPP_QR for row in connected):
                provider = "whatsapp_qr"
            else:
                provider = "whatsapp"

        phone = clean_phone_number(client.external_id) or client.external_id
        normalized = normalize_whatsapp(
            bot_id=bot.id,
            phone=phone,
            message_text="",
            client_name=client.first_name or client.username or phone,
            provider=provider,
            raw_payload={"operator_outbound": True},
        )
        if provider == "wazzup":
            preferred_channel_id = str(
                nested_payload.get("channel_id")
                or latest_payload.get("channel_id")
                or ""
            ).strip()
            wazzup_row = None
            if preferred_channel_id:
                wazzup_row = next(
                    (
                        row
                        for row in connected
                        if row.channel_type == HubChannelType.WAZZUP
                        and str(row.reference_id or "") == preferred_channel_id
                    ),
                    None,
                )
            if wazzup_row is None:
                wazzup_row = next(
                    (row for row in connected if row.channel_type == HubChannelType.WAZZUP),
                    None,
                )
            if wazzup_row is None:
                from app.services.wazzup_service import wazzup_service

                wazzup_row = await wazzup_service.get_channel(
                    db,
                    bot.id,
                    channel_id=preferred_channel_id or None,
                )
            if wazzup_row is not None:
                normalized.metadata["channel_id"] = str(wazzup_row.reference_id or "")
        return normalized

    return normalize_telegram(
        bot_id=bot.id,
        chat_id=client.external_id,
        message_text="",
        username=client.username or client.external_id,
        first_name=client.first_name or client.username or client.external_id,
        raw_payload={"operator_outbound": True},
    )
