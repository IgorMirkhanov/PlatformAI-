"""Kaspi Pay Celery side-effects — payment status only (no receipt OCR)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger

from app.core.database import async_session_factory
from app.models.integration_hub import IntegrationConnection
from app.services.integration_hub.hub_usage import record_hub_usage


async def _process_event(connection_id: str, payload: dict[str, Any]) -> dict[str, str]:
    async with async_session_factory() as db:
        connection = await db.get(IntegrationConnection, UUID(connection_id))
        if connection is None:
            return {"status": "missing"}
        await record_hub_usage(
            db,
            connection=connection,
            metric="kaspi_pay_webhook",
            quantity=1,
            meta={
                "type": payload.get("type"),
                "invoice_id": payload.get("invoice_id") or payload.get("order_id"),
                "status": payload.get("status"),
            },
        )
        await db.commit()
    logger.info(
        "KaspiPay.event_processed | connection_id={id} type={type} invoice={invoice} status={status}",
        id=connection_id,
        type=payload.get("type"),
        invoice=payload.get("invoice_id") or payload.get("order_id"),
        status=payload.get("status"),
    )
    return {"status": "ok"}
