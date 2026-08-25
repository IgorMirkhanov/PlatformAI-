"""Jivo, U-ON, and custom outbound webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
from loguru import logger

from app.models.core_models import Bot
from app.services.bot_app_integrations_service import _reveal_block, bot_app_integrations_service


async def transfer_jivo_to_operator(bot: Bot, *, chat_id: str, reason: str = "") -> dict[str, Any]:
    return await bot_app_integrations_service.send_jivo_message(
        bot,
        client_id=chat_id,
        text=reason or "Перевод на оператора",
    )


async def create_uon_travel_lead(
    bot: Bot,
    *,
    country: str,
    budget: str,
    dates: str,
    phone: str,
    client_name: str,
    comment: str = "",
) -> dict[str, Any]:
    note = " · ".join(p for p in (comment, dates, country) if p)
    return await bot_app_integrations_service.create_uon_lead(
        bot,
        name=client_name,
        phone=phone,
        note=note,
        destination=country,
        budget=budget,
    )


async def dispatch_custom_webhook(
    bot: Bot,
    *,
    event: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    config = _reveal_block("custom_webhook", bot_app_integrations_service._read_integration(bot, "custom_webhook"))
    if not config.get("connected"):
        raise ValueError("Custom webhook integration is not connected.")
    target_url = str(config.get("webhook_target_url") or "").strip()
    secret = str(config.get("hmac_secret") or config.get("webhook_secret") or "").strip()
    if not target_url:
        raise ValueError("Custom webhook URL is not configured.")

    body = {"event": event, "bot_id": str(bot.id), "payload": payload}
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        headers["X-MPAI-Signature"] = signature

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(target_url, content=raw, headers=headers)
        response.raise_for_status()

    logger.info("CustomWebhook.sent | bot_id={bot_id} event={event}", bot_id=bot.id, event=event)
    return {"status": "sent", "event": event, "target": target_url}
