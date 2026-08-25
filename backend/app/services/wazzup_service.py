"""Wazzup24 webhook intake + outbound message API (multi-channel aware)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import decrypt_credential
from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
from app.services.webhook_service import process_inbound_message

WAZZUP_API_BASE = (settings.WAZZUP_API_BASE_URL or "https://api.wazzup24.com/v3").rstrip("/")


class WazzupService:
    def extract_channel_id(self, body: dict[str, Any]) -> str | None:
        """Pull Wazzup ``channelId`` from a webhook payload (top-level or messages)."""
        top = body.get("channelId") or body.get("channel_id")
        if top:
            return str(top).strip() or None

        raw_items = body.get("messages")
        items: list[Any]
        if isinstance(raw_items, list):
            items = raw_items
        elif isinstance(body.get("message"), dict):
            items = [body["message"]]
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            cid = item.get("channelId") or item.get("channel_id")
            if cid:
                return str(cid).strip() or None
        return None

    async def get_channel_by_reference_id(
        self,
        db: AsyncSession,
        channel_id: str,
        *,
        require_connected: bool = True,
    ) -> BotChannel | None:
        """Resolve ``BotChannel`` by Wazzup channelId (``reference_id``)."""
        cid = (channel_id or "").strip()
        if not cid:
            return None
        conditions = [
            BotChannel.channel_type == HubChannelType.WAZZUP,
            BotChannel.reference_id == cid,
        ]
        if require_connected:
            conditions.append(BotChannel.status == HubChannelStatus.CONNECTED)
        result = await db.execute(
            select(BotChannel)
            .options(selectinload(BotChannel.bot))
            .where(*conditions)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_channel(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        channel_id: str | None = None,
    ) -> BotChannel | None:
        """
        Resolve the Wazzup ``BotChannel`` for outbound / inbound.

        Prefer exact ``reference_id`` match when ``channel_id`` is known so multi-channel
        bots never send with the wrong API key.
        """
        cid = (channel_id or "").strip() or None
        if cid:
            result = await db.execute(
                select(BotChannel).where(
                    BotChannel.bot_id == bot_id,
                    BotChannel.channel_type == HubChannelType.WAZZUP,
                    BotChannel.reference_id == cid,
                    BotChannel.status == HubChannelStatus.CONNECTED,
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                return row
            # Global lookup (shared webhook may resolve bot_id after channel match).
            global_row = await self.get_channel_by_reference_id(db, cid)
            if global_row is not None and global_row.bot_id == bot_id:
                return global_row

        result = await db.execute(
            select(BotChannel)
            .where(
                BotChannel.bot_id == bot_id,
                BotChannel.channel_type == HubChannelType.WAZZUP,
                BotChannel.status == HubChannelStatus.CONNECTED,
            )
            .order_by(BotChannel.updated_at.desc())
        )
        return result.scalars().first()

    def resolve_api_key(self, channel: BotChannel | None) -> str:
        """Decrypt tenant key from the channel row; platform env is last-resort fallback."""
        if channel is not None and channel.encrypted_token:
            try:
                return decrypt_credential(channel.encrypted_token)
            except Exception as exc:
                logger.error(
                    "WazzupService.decrypt_failed | channel_id={channel_id} error={error}",
                    channel_id=channel.reference_id,
                    error=str(exc),
                )
                return ""
        fallback = (settings.WAZZUP_API_KEY or "").strip()
        if fallback:
            logger.warning(
                "WazzupService.using_platform_api_key_fallback | bot_channel_missing_token=true"
            )
        return fallback

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

        default_channel = str(body.get("channelId") or body.get("channel_id") or "").strip()

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
                        "channel_id": str(
                            item.get("channelId") or item.get("channel_id") or default_channel or ""
                        ),
                    }
                )
        return messages

    async def process_queued_webhook(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        webhook_body: dict[str, Any],
        bot_channel_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        inbound_messages = self.extract_inbound_messages(webhook_body)
        first_channel_id = (
            (inbound_messages[0].get("channel_id") if inbound_messages else None)
            or self.extract_channel_id(webhook_body)
            or ""
        )

        channel: BotChannel | None = None
        if bot_channel_id is not None:
            channel = await db.get(BotChannel, bot_channel_id)
        if channel is None:
            channel = await self.get_channel(db, bot_id, channel_id=first_channel_id or None)
        if channel is None:
            return {"status": "ignored", "reason": "wazzup_not_connected"}

        # Hard isolation: never process under a mismatched bot_id.
        if channel.bot_id != bot_id:
            logger.warning(
                "WazzupService.bot_channel_mismatch | expected_bot={expected} actual_bot={actual} "
                "channel_id={channel_id}",
                expected=bot_id,
                actual=channel.bot_id,
                channel_id=channel.reference_id,
            )
            bot_id = channel.bot_id

        api_key = self.resolve_api_key(channel)
        channel_ref = channel.reference_id or first_channel_id or ""
        processed = 0
        for inbound in inbound_messages:
            inbound_channel_id = inbound.get("channel_id") or channel_ref
            # Per-message channel switch (batch webhooks covering multiple channelIds).
            if inbound_channel_id and inbound_channel_id != channel_ref:
                alt = await self.get_channel(db, bot_id, channel_id=inbound_channel_id)
                if alt is not None:
                    channel = alt
                    bot_id = alt.bot_id
                    api_key = self.resolve_api_key(alt)
                    channel_ref = alt.reference_id or inbound_channel_id

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
                    "channel_id": inbound_channel_id,
                    "bot_channel_id": str(channel.id),
                },
            )
            if result.response_text and not result.bot_silent and api_key:
                await self.send_text_message(
                    api_key=api_key,
                    chat_id=inbound["external_id"],
                    channel_id=inbound_channel_id or channel_ref,
                    text=result.response_text,
                )
            processed += 1
        return {
            "status": "processed",
            "messages_processed": processed,
            "bot_id": str(bot_id),
            "channel_id": channel_ref,
        }

    async def send_text_message(
        self,
        *,
        api_key: str,
        chat_id: str,
        channel_id: str,
        text: str,
    ) -> None:
        if not api_key:
            logger.error("WazzupService.send_skipped | reason=missing_api_key channel_id={cid}", cid=channel_id)
            return
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
