"""Client for the Baileys WhatsApp QR microservice + inbound processing helpers."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.schemas.media_schemas import MediaAttachment
from app.services.channels_service import channels_hub_service
from app.services.media_dispatch_service import deliver_attachments_safely
from app.services.webhook_service import process_inbound_message


class WhatsAppQrService:
    """Bridge FastAPI ↔ Node.js Baileys microservice on :3001."""

    @property
    def base_url(self) -> str:
        return settings.WHATSAPP_SERVICE_URL.rstrip("/")

    @staticmethod
    def _auth_headers() -> dict[str, str]:
        key = (getattr(settings, "INTERNAL_SERVICE_API_KEY", None) or "").strip()
        if not key:
            return {}
        return {"X-Internal-Api-Key": key}

    async def start_session(self, bot_id: uuid.UUID) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.base_url}/api/sessions/{bot_id}/start",
                headers=self._auth_headers(),
            )
            response.raise_for_status()
            return response.json()

    async def refresh_qr(self, bot_id: uuid.UUID) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                f"{self.base_url}/api/sessions/{bot_id}/refresh-qr",
                headers=self._auth_headers(),
            )
            response.raise_for_status()
            return response.json()

    async def get_session_status(self, bot_id: uuid.UUID) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/sessions/{bot_id}/status",
                    headers=self._auth_headers(),
                )
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            logger.warning(
                "WhatsAppQr.status_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            return {
                "bot_id": str(bot_id),
                "status": "disconnected",
                "phone": None,
                "push_name": None,
                "connected_at": None,
                "has_qr": False,
            }

    async def stop_session(self, bot_id: uuid.UUID) -> None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"{self.base_url}/api/sessions/{bot_id}/stop",
                    headers=self._auth_headers(),
                )
        except Exception as exc:
            logger.warning(
                "WhatsAppQr.stop_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )

    async def send_text_message(self, *, bot_id: uuid.UUID, to: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/api/send-message",
                headers=self._auth_headers(),
                json={"bot_id": str(bot_id), "to": to, "text": text},
            )
            if response.status_code >= 400:
                logger.error(
                    "WhatsAppQr.send_failed | status={status} body={body}",
                    status=response.status_code,
                    body=response.text[:500],
                )
                response.raise_for_status()

    async def send_media_message(
        self,
        *,
        bot_id: uuid.UUID,
        to: str,
        media_url: str,
        media_type: str = "document",
        caption: str | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> None:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{self.base_url}/api/send-media",
                headers=self._auth_headers(),
                json={
                    "bot_id": str(bot_id),
                    "to": to,
                    "media_url": media_url,
                    "media_type": media_type,
                    "caption": caption,
                    "filename": filename,
                    "mime_type": mime_type,
                },
            )
            if response.status_code >= 400:
                logger.error(
                    "WhatsAppQr.send_media_failed | status={status} body={body}",
                    status=response.status_code,
                    body=response.text[:500],
                )
                response.raise_for_status()

    async def dispatch_media_attachments(
        self,
        *,
        bot_id: uuid.UUID,
        to: str,
        attachments: list[Any],
        client_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> None:
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
                bot_id=bot_id,
                to=to,
                media_url=attachment.url,
                media_type=attachment.media_type,
                caption=attachment.caption,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
            )

        await deliver_attachments_safely(
            normalized,
            send_fn=_send_one,
            bot_id=bot_id,
            client_id=client_id,
            db=db,
        )

    async def process_inbound_webhook(
        self,
        db: AsyncSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        bot_id_raw = str(payload.get("bot_id") or "").strip()
        from_phone = str(payload.get("from") or "").strip()
        message_text = str(payload.get("message_text") or "").strip()
        push_name = str(payload.get("push_name") or from_phone).strip()

        if not bot_id_raw or not from_phone or not message_text:
            return {"status": "ignored", "reason": "incomplete_payload"}

        try:
            bot_id = uuid.UUID(bot_id_raw)
        except ValueError:
            return {"status": "ignored", "reason": "invalid_bot_id"}

        result = await process_inbound_message(
            db=db,
            bot_id=bot_id,
            external_id=from_phone,
            username=from_phone,
            first_name=push_name,
            message_text=message_text,
            source="whatsapp_qr",
            inbound_payload={
                "content_type": payload.get("content_type") or "text",
                "message_id": payload.get("message_id"),
                "remote_jid": payload.get("remote_jid"),
                "channel": "whatsapp_qr",
            },
        )

        if result.bot_silent or not result.response_text:
            return {
                "status": "processed",
                "bot_silent": True,
                "client_id": str(result.client_id),
            }

        await self.send_text_message(
            bot_id=bot_id,
            to=from_phone,
            text=result.response_text,
        )
        if result.media_attachments:
            await self.dispatch_media_attachments(
                bot_id=bot_id,
                to=from_phone,
                attachments=list(result.media_attachments),
                client_id=result.client_id,
                db=db,
            )
        return {
            "status": "processed",
            "client_id": str(result.client_id),
            "response_text": result.response_text,
            "media_attachments": len(result.media_attachments or []),
        }

    async def mark_connected_from_frame(
        self,
        bot_id: uuid.UUID,
        *,
        session_id: str | None,
        phone: str | None,
    ) -> None:
        async with async_session_factory() as db:
            try:
                await channels_hub_service.complete_whatsapp_qr_session(
                    db,
                    bot_id,
                    session_id=session_id or str(bot_id),
                    session_token=f"baileys_live:{session_id or bot_id}",
                    phone=phone,
                )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.exception(
                    "WhatsAppQr.persist_connected_failed | bot_id={bot_id} error={error}",
                    bot_id=bot_id,
                    error=str(exc),
                )


whatsapp_qr_service = WhatsAppQrService()
