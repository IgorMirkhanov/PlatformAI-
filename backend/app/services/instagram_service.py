"""Instagram Direct webhook intake + Graph API outbound replies."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_credential
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.models.core_models import Bot
from app.services.webhook_service import process_inbound_message


class InstagramService:
    async def get_channel(self, db: AsyncSession, bot_id: uuid.UUID) -> BotChannel | None:
        result = await db.execute(
            select(BotChannel).where(
                BotChannel.bot_id == bot_id,
                BotChannel.channel_type == HubChannelType.INSTAGRAM,
                BotChannel.status == HubChannelStatus.CONNECTED,
            )
        )
        return result.scalar_one_or_none()

    async def get_bot_by_page_id(self, db: AsyncSession, page_id: str) -> Bot | None:
        result = await db.execute(
            select(BotChannel).where(
                BotChannel.channel_type == HubChannelType.INSTAGRAM,
                BotChannel.reference_id == page_id,
                BotChannel.status == HubChannelStatus.CONNECTED,
            )
        )
        channel = result.scalar_one_or_none()
        if channel is None:
            return None
        bot_result = await db.execute(select(Bot).where(Bot.id == channel.bot_id))
        return bot_result.scalar_one_or_none()

    def extract_inbound_messages(self, body: dict[str, Any]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for entry in body.get("entry") or []:
            for event in entry.get("messaging") or []:
                sender = (event.get("sender") or {}).get("id")
                text = ((event.get("message") or {}).get("text") or "").strip()
                if sender and text:
                    messages.append(
                        {
                            "external_id": str(sender),
                            "message_text": text,
                            "username": str(sender),
                            "first_name": str(sender),
                        }
                    )
        return messages

    async def process_queued_webhook(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        webhook_body: dict[str, Any],
    ) -> dict[str, Any]:
        channel = await self.get_channel(db, bot_id)
        if channel is None:
            return {"status": "ignored", "reason": "instagram_not_connected"}

        token = decrypt_credential(channel.encrypted_token) if channel.encrypted_token else ""
        inbound_messages = self.extract_inbound_messages(webhook_body)
        processed = 0
        for inbound in inbound_messages:
            result = await process_inbound_message(
                db=db,
                bot_id=bot_id,
                external_id=inbound["external_id"],
                username=inbound["username"],
                first_name=inbound["first_name"],
                message_text=inbound["message_text"],
                source="instagram",
                inbound_payload={"channel": "instagram"},
            )
            if result.response_text and not result.bot_silent and token:
                await self.send_text_message(
                    access_token=token,
                    recipient_id=inbound["external_id"],
                    text=result.response_text,
                )
            processed += 1
        return {"status": "processed", "messages_processed": processed}

    async def send_text_message(
        self,
        *,
        access_token: str,
        recipient_id: str,
        text: str,
    ) -> None:
        url = "https://graph.facebook.com/v19.0/me/messages"
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text[:2000]},
            "messaging_type": "RESPONSE",
        }
        params = {"access_token": access_token}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, params=params, json=payload)
            if response.status_code >= 400:
                logger.error(
                    "InstagramService.send_failed | status={status} body={body}",
                    status=response.status_code,
                    body=response.text[:500],
                )
                response.raise_for_status()


instagram_service = InstagramService()
