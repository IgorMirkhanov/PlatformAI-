"""amoCRM inbound events — match account, ACK 200, enqueue."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Request, Response, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_hub import IntegrationConnection
from app.services.integration_hub.adapters.amocrm import parse_amocrm_webhook
from app.services.integration_hub.adapters.bitrix24 import flatten_form_dict
from app.services.webhook_processor import enqueue_if_needed, process_hub_inbound_event


async def _form_payload(request: Request) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    raw = await request.body()
    if "json" in content_type:
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
    try:
        form = await request.form()
    except Exception:
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    flat: dict[str, Any] = {}
    for key, value in form.items():
        flat[str(key)] = "" if hasattr(value, "filename") else str(value)
    return flatten_form_dict(flat)


def _account_matches(connection: IntegrationConnection, parsed: dict[str, Any]) -> bool:
    expected_host = str(
        (connection.config_json or {}).get("subdomain") or connection.external_account_id or ""
    ).lower()
    expected_host = expected_host.replace("https://", "").replace("http://", "").split(".")[0]
    got_sub = str(parsed.get("subdomain") or "").lower().split(".")[0]
    if got_sub and expected_host and got_sub != expected_host:
        return False
    expected_id = str((connection.config_json or {}).get("account_id") or "")
    got_id = str(parsed.get("account_id") or "")
    if expected_id and got_id and expected_id != got_id:
        return False
    return True


async def ingest_amocrm_webhook(
    *,
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession,
) -> Response:
    payload = await _form_payload(request)
    parsed = parse_amocrm_webhook(payload)
    connection = await db.get(IntegrationConnection, connection_id)
    if connection is None or connection.provider not in {"amocrm", "kommo"}:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    if not _account_matches(connection, parsed):
        logger.warning(
            "amoCRM.webhook_account_mismatch | connection_id={id}",
            id=connection_id,
        )
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    events = parsed.get("events") or []
    if not events:
        return Response(status_code=status.HTTP_200_OK)

    queued: list = []
    for event in events:
        if not isinstance(event, dict):
            continue
        external_event_id = (
            f"{connection_id}:{event.get('entity')}:{event.get('action')}:"
            f"{event.get('entity_id')}:{event.get('updated_at')}"
        )
        result = await process_hub_inbound_event(
            db,
            connection=connection,
            provider=connection.provider,
            external_event_id=external_event_id,
            payload=event,
        )
        queued.append(result)
    await db.commit()
    for result in queued:
        enqueue_if_needed(result)
    return Response(status_code=status.HTTP_200_OK)
