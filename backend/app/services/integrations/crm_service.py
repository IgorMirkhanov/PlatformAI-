"""CRM integration helpers (Bitrix24, amoCRM/Kommo)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot
from app.services.crm.save_lead_tool import save_lead_to_crm


async def save_lead_to_crm_integration(
    db: AsyncSession,
    *,
    bot: Bot,
    phone: str | None = None,
    client_name: str | None = None,
    comment: str | None = None,
    channel: str = "web",
    channel_user_id: str | None = None,
) -> dict[str, Any]:
    return await save_lead_to_crm(
        db,
        bot=bot,
        phone=phone,
        client_name=client_name,
        comment=comment,
        channel=channel,
        channel_user_id=channel_user_id,
    )


async def get_deal_status(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    deal_id: str,
    platform: str = "bitrix24",
) -> dict[str, Any]:
    from app.models.integrations import get_bitrix_webhook_url
    from app.models.core_models import Bot
    import httpx

    bot = await db.get(Bot, bot_id)
    if bot is None:
        return {"status": "error", "message": "Bot not found"}
    if platform == "bitrix24":
        webhook = get_bitrix_webhook_url(bot)
        if not webhook:
            return {"status": "error", "message": "Bitrix24 is not connected"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{webhook}crm.deal.get", params={"id": deal_id})
            response.raise_for_status()
            data = response.json()
        result = data.get("result") if isinstance(data, dict) else None
        return {
            "status": "ok",
            "deal_id": deal_id,
            "stage_id": result.get("STAGE_ID") if isinstance(result, dict) else None,
            "title": result.get("TITLE") if isinstance(result, dict) else None,
        }
    return {"status": "error", "message": f"Unsupported CRM platform: {platform}"}


async def create_amocrm_lead(
    db: AsyncSession,
    *,
    bot: Bot,
    pipeline_id: str | None = None,
    phone: str | None = None,
    client_name: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    note = comment or ""
    if pipeline_id:
        note = f"{note} | pipeline_id={pipeline_id}".strip(" |")
    return await save_lead_to_crm(
        db,
        bot=bot,
        phone=phone,
        client_name=client_name,
        comment=note or None,
        channel="crm",
        channel_user_id=None,
    )
