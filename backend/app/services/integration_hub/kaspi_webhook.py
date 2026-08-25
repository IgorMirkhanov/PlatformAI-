"""Kaspi Pay inbound — verify signature, ACK 200, enqueue payment.updated."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Request, Response, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_hub import IntegrationConnection
from app.services.integration_hub.adapters.bitrix24 import flatten_form_dict
from app.services.integration_hub.adapters.kaspi import KaspiPayHubAdapter
from app.services.integration_hub.oauth import secrets_from_connection_with_vault
from app.services.webhook_processor import enqueue_if_needed, process_hub_inbound_event

_SIGNATURE_HEADERS = (
    "x-kaspi-signature",
    "x-webhook-signature",
    "x-signature",
    "x-hub-signature-256",
)


async def _payload_and_raw(request: Request) -> tuple[dict[str, Any], bytes]:
    content_type = (request.headers.get("content-type") or "").lower()
    raw = await request.body()
    if "json" in content_type or not content_type:
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            return data, raw
        return {}, raw
    try:
        form = await request.form()
    except Exception:
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
            return (data if isinstance(data, dict) else {}), raw
        except Exception:
            return {}, raw
    flat: dict[str, Any] = {}
    for key, value in form.items():
        flat[str(key)] = "" if hasattr(value, "filename") else str(value)
    return flatten_form_dict(flat), raw


def _signature_header(request: Request) -> str | None:
    for name in _SIGNATURE_HEADERS:
        value = request.headers.get(name)
        if value:
            return value
    return None


async def ingest_kaspi_pay_webhook(
    *,
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession,
) -> Response:
    payload, raw_body = await _payload_and_raw(request)
    if payload.get("test") is True or payload.get("event") == "webhook.test":
        return Response(status_code=status.HTTP_200_OK)

    connection = await db.get(IntegrationConnection, connection_id)
    if connection is None or connection.provider != "kaspi_pay":
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    adapter = KaspiPayHubAdapter()
    try:
        secrets = await secrets_from_connection_with_vault(db, connection)
    except Exception:
        logger.warning("KaspiPay.webhook_secrets_unreadable | connection_id={id}", id=connection_id)
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    secret = str((secrets.extra or {}).get("secret_key") or (secrets.extra or {}).get("webhook_secret") or "")
    header = _signature_header(request)
    if secret:
        if not adapter.verify_webhook_signature(
            secrets=secrets, raw_body=raw_body, signature_header=header
        ):
            return Response(status_code=status.HTTP_403_FORBIDDEN)
    elif not adapter.merchant_matches(secrets, payload):
        logger.warning("KaspiPay.webhook_merchant_mismatch | connection_id={id}", id=connection_id)
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    event = adapter.parse_incoming_webhook(payload, connection_id=connection.id)
    external_event_id = (
        event.transaction_id
        or f"{connection.id}:{event.invoice_id}:{event.status}:{event.timestamp}"
    )
    result = await process_hub_inbound_event(
        db,
        connection=connection,
        provider="kaspi_pay",
        external_event_id=str(external_event_id),
        payload=event.as_dict(),
    )
    await db.commit()
    enqueue_if_needed(result)
    return Response(status_code=status.HTTP_200_OK)
