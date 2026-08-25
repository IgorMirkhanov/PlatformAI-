"""Wazzup hub inbound — test ping 200, parse message.received, persist received, queue."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_hub import IntegrationConnection
from app.services.integration_hub.adapters.wazzup import WazzupHubAdapter
from app.services.webhook_processor import enqueue_if_needed, process_hub_inbound_event


async def ingest_wazzup_hub_webhook(
    *,
    connection_id: uuid.UUID,
    payload: dict[str, Any],
    db: AsyncSession,
) -> Response:
    if payload.get("test") is True:
        return Response(status_code=status.HTTP_200_OK)

    connection = await db.get(IntegrationConnection, connection_id)
    if connection is None or connection.provider != "wazzup":
        raise LookupError("not a hub wazzup connection")

    events = WazzupHubAdapter().parse_incoming_webhook(payload, connection_id=connection.id)
    if not events:
        return Response(status_code=status.HTTP_200_OK)

    results = []
    for event in events:
        external_event_id = event.message_id or (
            f"{connection.id}:{event.channel_id}:{event.chat_id}:{event.timestamp}"
        )
        result = await process_hub_inbound_event(
            db,
            connection=connection,
            provider="wazzup",
            external_event_id=str(external_event_id),
            payload=event.as_dict(),
        )
        results.append(result)
    await db.commit()
    for result in results:
        enqueue_if_needed(result)
    return Response(status_code=status.HTTP_200_OK)
