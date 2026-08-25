"""Kaspi Pay invoicing and receipt OCR verification."""

from __future__ import annotations

from typing import Any

from app.models.core_models import Bot
from app.services.bot_app_integrations_service import bot_app_integrations_service


async def create_kaspi_invoice(
    bot: Bot,
    *,
    amount_kzt: float,
    description: str,
    order_id: str | None = None,
) -> dict[str, Any]:
    resolved_order = order_id or f"ord-{int(amount_kzt)}"
    return await bot_app_integrations_service.create_kaspi_invoice(
        bot,
        amount_kzt=amount_kzt,
        order_id=resolved_order,
        description=description,
    )


async def verify_kaspi_receipt_text(bot: Bot, *, text: str) -> dict[str, Any]:
    _ = bot
    return await bot_app_integrations_service.verify_kaspi_receipt_text(text)


async def verify_kaspi_receipt_bytes(bot: Bot, *, content: bytes, filename: str) -> dict[str, Any]:
    _ = bot
    return await bot_app_integrations_service.verify_kaspi_receipt_file(content, filename)
