"""Bitrix24 Celery queue — inbound events, event.bind chain, outbound REST retries.

Portal REST is capped at 2 req/s. Tasks retry with countdown instead of spinning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from loguru import logger

from app.core.celery_app import celery_app
from app.core.database import async_session_factory, run_celery_async
from app.models.integration_hub import (
    HubConnectionStatus,
    IntegrationConnection,
)
from app.services.integration_hub.adapters.bitrix24 import CRM_EVENT_HANDLERS, Bitrix24HubAdapter
from app.services.integration_hub.bitrix_portal import BitrixPortalRateLimited
from app.services.integration_hub.hub_usage import record_hub_usage
from app.services.integration_hub.oauth import secrets_from_connection_with_vault


@celery_app.task(
    bind=True,
    name="app.tasks.bitrix24_tasks.process_bitrix24_event_task",
    max_retries=8,
    acks_late=True,
)
def process_bitrix24_event_task(
    self,
    connection_id: str,
    event: str,
    payload: dict[str, Any],
) -> dict[str, str]:
    try:
        return run_celery_async(_process_event(connection_id, event, payload))
    except BitrixPortalRateLimited as exc:
        raise self.retry(exc=exc, countdown=min(60, 2 ** int(self.request.retries or 0))) from exc


@celery_app.task(
    bind=True,
    name="app.tasks.bitrix24_tasks.bind_bitrix24_events_task",
    max_retries=12,
    acks_late=True,
)
def bind_bitrix24_events_task(self, connection_id: str, event_index: int = 0) -> dict[str, str]:
    try:
        return run_celery_async(_bind_one_event(connection_id, int(event_index or 0)))
    except BitrixPortalRateLimited as exc:
        raise self.retry(exc=exc, countdown=1) from exc


@celery_app.task(
    bind=True,
    name="app.tasks.bitrix24_tasks.execute_bitrix_rest_task",
    max_retries=12,
    acks_late=True,
)
def execute_bitrix_rest_task(
    self,
    connection_id: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        return run_celery_async(_execute_rest(connection_id, method, params or {}))
    except BitrixPortalRateLimited as exc:
        raise self.retry(exc=exc, countdown=1) from exc


async def _process_event(connection_id: str, event: str, payload: dict[str, Any]) -> dict[str, str]:
    event_key = (event or "").upper()
    async with async_session_factory() as db:
        connection = await db.get(IntegrationConnection, UUID(connection_id))
        if connection is None:
            return {"status": "missing"}
        if event_key == "ONAPPUNINSTALL":
            from app.services.integration_hub.oauth import mark_connection_revoked

            await mark_connection_revoked(
                db,
                connection,
                reason="bitrix24:ONAPPUNINSTALL",
            )
            await record_hub_usage(
                db,
                connection=connection,
                metric="bitrix24_webhook",
                quantity=1,
                meta={"event": event_key},
            )
            await db.commit()
            logger.info(
                "Bitrix24.app_uninstalled | connection_id={id}",
                id=connection_id,
            )
            return {"status": "revoked", "event": event_key}
        await record_hub_usage(
            db,
            connection=connection,
            metric="bitrix24_webhook",
            quantity=1,
            meta={"event": event_key},
        )
        await db.commit()
    logger.info(
        "Bitrix24.event_processed | connection_id={id} event={event}",
        id=connection_id,
        event=event_key,
    )
    _ = payload
    return {"status": "ok", "event": event_key}


async def _bind_one_event(connection_id: str, event_index: int) -> dict[str, str]:
    from app.core.config import resolve_webhook_base_url, settings

    if event_index < 0 or event_index >= len(CRM_EVENT_HANDLERS):
        return {"status": "done"}
    event = CRM_EVENT_HANDLERS[event_index]
    async with async_session_factory() as db:
        connection = await db.get(IntegrationConnection, UUID(connection_id))
        if connection is None or connection.status != HubConnectionStatus.CONNECTED.value:
            return {"status": "skipped"}
        secrets = await secrets_from_connection_with_vault(db, connection)
        adapter = Bitrix24HubAdapter()
        handler = f"{resolve_webhook_base_url()}/api/v1/webhooks/bitrix24/{connection.id}"
        async with httpx.AsyncClient(timeout=20.0) as http:
            await adapter.rest_call(
                secrets=secrets,
                http=http,
                connection_id=connection.id,
                method="event.bind",
                params={"EVENT": event, "HANDLER": handler},
            )
    nxt = event_index + 1
    if nxt < len(CRM_EVENT_HANDLERS):
        bind_bitrix24_events_task.apply_async(
            args=[connection_id, nxt],
            countdown=1,
            queue=settings.CELERY_CRM_QUEUE,
        )
    return {"status": "bound", "event": event}


async def _execute_rest(connection_id: str, method: str, params: dict[str, Any]) -> Any:
    async with async_session_factory() as db:
        connection = await db.get(IntegrationConnection, UUID(connection_id))
        if connection is None:
            return None
        secrets = await secrets_from_connection_with_vault(db, connection)
        adapter = Bitrix24HubAdapter()
        async with httpx.AsyncClient(timeout=20.0) as http:
            return await adapter.rest_call(
                secrets=secrets,
                http=http,
                connection_id=connection.id,
                method=method,
                params=params,
            )
