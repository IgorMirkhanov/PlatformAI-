from __future__ import annotations

import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_credential
from app.models.core_models import Bot, DiagnosticErrorType
from app.schemas.webhook_schemas import (
    ParsedWhatsAppInbound,
    WhatsAppWebhookPayload,
)
from app.services.diagnostic_log_service import diagnostic_log_service
from app.services.messenger_errors import (
    MessengerAPIError,
    format_messenger_diagnostic,
    messenger_error_is_retriable,
)
from app.services.webhook_service import process_inbound_message


class WhatsAppService:
    """WhatsApp Cloud API webhook processor for queued inbound messages."""

    async def get_bot_by_id(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> Bot | None:
        result = await db.execute(
            select(Bot).where(Bot.id == bot_id, Bot.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_bot_by_token_hash(
        self,
        db: AsyncSession,
        token_hash: str,
    ) -> Bot | None:
        if not token_hash:
            return None

        result = await db.execute(
            select(Bot).where(
                Bot.is_active.is_(True),
                Bot.credentials["token_hash"].as_string() == token_hash,
            )
        )
        bot = result.scalar_one_or_none()
        if bot is not None:
            return bot

        result = await db.execute(select(Bot).where(Bot.is_active.is_(True)))
        for candidate in result.scalars().all():
            credentials = candidate.credentials if isinstance(candidate.credentials, dict) else {}
            if credentials.get("token_hash") == token_hash:
                return candidate
            channels = credentials.get("channels") if isinstance(credentials.get("channels"), dict) else {}
            whatsapp_channel = channels.get("whatsapp") if isinstance(channels.get("whatsapp"), dict) else {}
            if whatsapp_channel.get("token_hash") == token_hash:
                return candidate
        return None

    @staticmethod
    def get_verify_token(bot: Bot) -> str | None:
        credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
        token = credentials.get("whatsapp_verify_token") or credentials.get("verify_token")
        if token:
            return str(token)
        channels = credentials.get("channels") if isinstance(credentials.get("channels"), dict) else {}
        whatsapp_channel = channels.get("whatsapp") if isinstance(channels.get("whatsapp"), dict) else {}
        nested = whatsapp_channel.get("whatsapp_verify_token") or whatsapp_channel.get("verify_token")
        return str(nested) if nested else None

    def extract_typed_inbound_messages(
        self,
        webhook_body: WhatsAppWebhookPayload | dict[str, Any],
    ) -> list[ParsedWhatsAppInbound]:
        if isinstance(webhook_body, dict):
            try:
                webhook_body = WhatsAppWebhookPayload.model_validate(webhook_body)
            except Exception:
                return [
                    ParsedWhatsAppInbound(
                        external_id=str(item["external_id"]),
                        username=str(item.get("username") or item["external_id"]),
                        first_name=str(item.get("first_name") or item["external_id"]),
                        last_name="",
                        message_text=str(item.get("message_text") or ""),
                        content_type=str(item.get("content_type") or "text"),
                    )
                    for item in self.extract_inbound_messages(webhook_body)
                ]

        messages: list[ParsedWhatsAppInbound] = []
        for entry in webhook_body.entry:
            for change in entry.changes:
                value = change.value
                contact_names: dict[str, str] = {}
                for contact in value.contacts:
                    wa_id = str(contact.wa_id or "")
                    profile_name = (contact.profile.name if contact.profile else None) or ""
                    if wa_id:
                        contact_names[wa_id] = profile_name

                for message in value.messages:
                    sender = str(message.from_ or "")
                    if not sender:
                        continue

                    message_type = str(message.type or "text")
                    if message_type == "text":
                        text_body = str(message.text.body if message.text else "")
                    else:
                        text_body = f"[User sent {message_type}]"

                    profile_name = contact_names.get(sender, "")
                    name_parts = profile_name.split(maxsplit=1) if profile_name else []
                    first_name = name_parts[0] if name_parts else sender
                    last_name = name_parts[1] if len(name_parts) > 1 else ""

                    messages.append(
                        ParsedWhatsAppInbound(
                            external_id=sender,
                            username=sender,
                            first_name=first_name,
                            last_name=last_name,
                            message_text=text_body,
                            content_type=message_type,
                        )
                    )
        return messages

    def extract_inbound_messages(self, webhook_body: dict[str, Any]) -> list[dict[str, Any]]:
        typed = self.extract_typed_inbound_messages(webhook_body)
        return [
            {
                "external_id": item.external_id,
                "username": item.username,
                "first_name": item.first_name,
                "last_name": item.last_name,
                "message_text": item.message_text,
                "content_type": item.content_type,
                "raw_message": {},
            }
            for item in typed
        ]

    async def process_queued_webhook(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID | None = None,
        token_hash: str | None = None,
        webhook_body: dict[str, Any],
    ) -> dict[str, Any]:
        bot: Bot | None = None
        if bot_id is not None:
            bot = await self.get_bot_by_id(db, bot_id)
        elif token_hash:
            bot = await self.get_bot_by_token_hash(db, token_hash)

        if bot is None:
            logger.warning(
                "WhatsAppService.unknown_bot | bot_id={bot_id} token_hash={token_hash}",
                bot_id=bot_id,
                token_hash=(token_hash or "")[:12],
            )
            return {"status": "ignored", "reason": "unknown_bot"}

        inbound_messages = self.extract_typed_inbound_messages(webhook_body)
        if not inbound_messages:
            logger.debug("WhatsAppService.no_messages | bot_id={bot_id}", bot_id=bot.id)
            return {"status": "ignored", "reason": "no_messages"}

        credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
        channels = credentials.get("channels") if isinstance(credentials.get("channels"), dict) else {}
        whatsapp_channel = channels.get("whatsapp") if isinstance(channels.get("whatsapp"), dict) else {}

        access_token_encrypted = (
            credentials.get("whatsapp_access_token")
            or whatsapp_channel.get("whatsapp_access_token")
        )
        phone_number_id = (
            credentials.get("whatsapp_phone_number_id")
            or whatsapp_channel.get("whatsapp_phone_number_id")
        )

        processed = 0
        for inbound in inbound_messages:
            display_name = " ".join(
                part for part in (inbound.first_name, inbound.last_name) if part
            ).strip() or inbound.first_name

            result = await process_inbound_message(
                db=db,
                bot_id=bot.id,
                external_id=inbound.external_id,
                username=inbound.username,
                first_name=display_name,
                message_text=inbound.message_text,
                source="whatsapp",
                inbound_payload={
                    "content_type": inbound.content_type,
                    "last_name": inbound.last_name,
                    "channel": "whatsapp",
                },
            )

            if (
                not result.bot_silent
                and result.response_text
                and access_token_encrypted
                and phone_number_id
            ):
                try:
                    token = decrypt_credential(str(access_token_encrypted))
                    phone_id = str(phone_number_id)
                    await self.send_text_message(
                        access_token=token,
                        phone_number_id=phone_id,
                        recipient=inbound.external_id,
                        text=result.response_text,
                        bot_id=bot.id,
                        client_id=result.client_id,
                        db=db,
                    )
                    if result.media_attachments:
                        await self.dispatch_media_attachments(
                            access_token=token,
                            phone_number_id=phone_id,
                            recipient=inbound.external_id,
                            attachments=list(result.media_attachments),
                            bot_id=bot.id,
                            client_id=result.client_id,
                            db=db,
                        )
                except MessengerAPIError:
                    # Abort remaining outbound sends; diagnostic already persisted.
                    raise
            processed += 1

        return {"status": "processed", "messages_processed": processed}

    async def verify_access_token(
        self,
        *,
        access_token: str,
        phone_number_id: str,
    ) -> dict[str, Any]:
        """Validate WABA credentials against Graph API before persisting."""
        url = f"https://graph.facebook.com/v19.0/{phone_number_id}"
        params = {
            "fields": "id,display_phone_number,verified_name",
            "access_token": access_token,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, params=params)
                if response.status_code >= 400:
                    detail = response.text[:300]
                    try:
                        err = response.json().get("error", {})
                        detail = str(err.get("message") or detail)
                    except Exception:
                        pass
                    raise ValueError(f"WABA authorization failed: {detail}")
                return response.json()
        except httpx.TimeoutException as exc:
            raise TimeoutError("Connection timed out. Please check your token.") from exc

    async def send_text_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        recipient: str,
        text: str,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> None:
        """Post a text message to Meta WhatsApp Cloud API for the customer phone id."""
        url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": text[:4096]},
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code >= 400:
                    await self._raise_messenger_failure(
                        status_code=response.status_code,
                        body=response.text,
                        bot_id=bot_id,
                        client_id=client_id,
                        db=db,
                    )
        except MessengerAPIError:
            raise
        except httpx.HTTPError as exc:
            await self._raise_messenger_failure(
                status_code=None,
                body=str(exc),
                bot_id=bot_id,
                client_id=client_id,
                db=db,
            )

        logger.info("WhatsAppService.sent | recipient={recipient}", recipient=recipient)

    async def send_media_message(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        recipient: str,
        media_type: str,
        media_url: str,
        caption: str | None = None,
        filename: str | None = None,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> None:
        """Send image/document via WhatsApp Cloud API link upload."""
        url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
        kind = media_type if media_type in {"image", "document", "video", "audio"} else "document"
        body: dict[str, Any] = {"link": media_url}
        if caption and kind in {"image", "document", "video"}:
            body["caption"] = caption[:1024]
        if filename and kind == "document":
            body["filename"] = filename[:255]

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": kind,
            kind: body,
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                await self._raise_messenger_failure(
                    status_code=response.status_code,
                    body=response.text,
                    bot_id=bot_id,
                    client_id=client_id,
                    db=db,
                )

    async def dispatch_media_attachments(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        recipient: str,
        attachments: list[Any],
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> None:
        from app.schemas.media_schemas import MediaAttachment
        from app.services.media_dispatch_service import deliver_attachments_safely

        normalized: list[MediaAttachment] = []
        for item in attachments:
            if isinstance(item, MediaAttachment):
                normalized.append(item)
            else:
                try:
                    normalized.append(MediaAttachment.model_validate(item))
                except Exception:
                    continue

        async def _send_one(attachment: MediaAttachment) -> None:
            await self.send_media_message(
                access_token=access_token,
                phone_number_id=phone_number_id,
                recipient=recipient,
                media_type=attachment.media_type,
                media_url=attachment.url,
                caption=attachment.caption,
                filename=attachment.filename,
                bot_id=bot_id,
                client_id=client_id,
                db=db,
            )

        await deliver_attachments_safely(
            normalized,
            send_fn=_send_one,
            bot_id=bot_id,
            client_id=client_id,
            db=db,
        )

    async def _raise_messenger_failure(
        self,
        *,
        status_code: int | None,
        body: str,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        db: AsyncSession | None,
    ) -> None:
        detail = format_messenger_diagnostic(
            channel="WhatsApp",
            status_code=status_code,
            body=body,
        )
        logger.error(
            "WhatsAppService.send_failed | status={status} body={body}",
            status=status_code,
            body=(body or "")[:500],
        )
        if bot_id is not None:
            try:
                if db is not None:
                    await diagnostic_log_service.log(
                        db,
                        bot_id=bot_id,
                        client_id=client_id,
                        error_type=DiagnosticErrorType.MESSENGER_API_ERROR,
                        error_message=detail,
                    )
                else:
                    diagnostic_log_service.schedule_log(
                        bot_id=bot_id,
                        client_id=client_id,
                        error_type=DiagnosticErrorType.MESSENGER_API_ERROR,
                        error_message=detail,
                    )
            except Exception as log_exc:
                logger.exception(
                    "WhatsAppService.diagnostic_log_failed | error={error}",
                    error=str(log_exc),
                )
        raise MessengerAPIError(
            channel="whatsapp",
            status_code=status_code,
            detail=detail,
            retriable=messenger_error_is_retriable(status_code),
        )


whatsapp_service = WhatsAppService()
