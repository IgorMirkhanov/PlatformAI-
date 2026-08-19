"""Wazzup24 webhook intake + outbound message API."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_credential
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.services.webhook_service import process_inbound_message

WAZZUP_API_BASE = "https://api.wazzup24.com/v3"


class WazzupService:
    async def get_channel(self, db: AsyncSession, bot_id: uuid.UUID) -> BotChannel | None:
        result = await db.execute(
            select(BotChannel).where(
                BotChannel.bot_id == bot_id,
                BotChannel.channel_type == HubChannelType.WAZZUP,
                BotChannel.status == HubChannelStatus.CONNECTED,
            )
        )
        return result.scalar_one_or_none()

    def extract_inbound_messages(self, body: dict[str, Any]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        # Wazzup can send { messages: [...] } or a single message object.
        raw_items = body.get("messages")
        if isinstance(raw_items, list):
            items = raw_items
        elif isinstance(body.get("message"), dict):
            items = [body["message"]]
        elif body.get("chatId") or body.get("chat_id"):
            items = [body]
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            # Skip company outbound echoes — prevents bot reply loops.
            if item.get("isOutbound") is True or str(item.get("direction") or "").lower() == "outgoing":
                continue
            if str(item.get("status") or "").lower() in {"sent", "delivered", "read", "outgoing"}:
                if not str(
                    item.get("text")
                    or item.get("message")
                    or ((item.get("content") or {}).get("text") if isinstance(item.get("content"), dict) else "")
                    or ""
                ).strip():
                    continue
            chat_id = str(item.get("chatId") or item.get("chat_id") or item.get("from") or "").strip()
            text = str(
                item.get("text")
                or item.get("message")
                or ((item.get("content") or {}).get("text") if isinstance(item.get("content"), dict) else "")
                or ""
            ).strip()
            # Skip outbound echoes when status is present without text
            if item.get("status") and not text:
                continue
            if chat_id and text:
                messages.append(
                    {
                        "external_id": chat_id,
                        "message_text": text,
                        "username": chat_id,
                        "first_name": str(item.get("contactName") or item.get("name") or chat_id),
                        "channel_id": str(item.get("channelId") or item.get("channel_id") or ""),
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
            return {"status": "ignored", "reason": "wazzup_not_connected"}

        api_key = decrypt_credential(channel.encrypted_token) if channel.encrypted_token else ""
        channel_id = channel.reference_id or ""
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
                source="wazzup",
                inbound_payload={
                    "channel": "whatsapp",
                    "provider": "wazzup",
                    "phone": inbound["external_id"],
                },
            )
            if result.response_text and not result.bot_silent and api_key:
                await self.send_text_message(
                    api_key=api_key,
                    chat_id=inbound["external_id"],
                    channel_id=inbound.get("channel_id") or channel_id,
                    text=result.response_text,
                )
            processed += 1
        return {"status": "processed", "messages_processed": processed}

    async def send_text_message(
        self,
        *,
        api_key: str,
        chat_id: str,
        channel_id: str,
        text: str,
    ) -> None:
        url = f"{WAZZUP_API_BASE}/message"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "chatId": chat_id,
            "chatType": "whatsapp",
            "text": text[:4096],
        }
        if channel_id:
            payload["channelId"] = channel_id

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                logger.error(
                    "WazzupService.send_failed | status={status} body={body}",
                    status=response.status_code,
                    body=response.text[:500],
                )
                response.raise_for_status()


wazzup_service = WazzupService()
