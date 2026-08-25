"""amoCRM Celery queue — webhook ingest, event subscription, 429 backoff retries."""

from __future__ import annotations

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
from app.services.integration_hub.amocrm_account import AmoCRMAccountRateLimited
from app.services.integration_hub.adapters.amocrm import AmoCRMHubAdapter
from app.services.integration_hub.hub_usage import record_hub_usage
from app.services.integration_hub.oauth import secrets_from_connection_with_vault


@celery_app.task(
    bind=True,
    name="app.tasks.amocrm_tasks.process_amocrm_event_task",
    max_retries=8,
    acks_late=True,
)
def process_amocrm_event_task(self, connection_id: str, payload: dict[str, Any]) -> dict[str, str]:
    try:
        return run_celery_async(_process_event(connection_id, payload))
    except AmoCRMAccountRateLimited as exc:
        raise self.retry(exc=exc, countdown=min(60, 2 ** int(self.request.retries or 0))) from exc


@celery_app.task(
    bind=True,
    name="app.tasks.amocrm_tasks.bind_amocrm_webhooks_task",
    max_retries=8,
    acks_late=True,
)
def bind_amocrm_webhooks_task(self, connection_id: str) -> dict[str, str]:
    try:
        return run_celery_async(_bind_webhooks(connection_id))
    except AmoCRMAccountRateLimited as exc:
        raise self.retry(exc=exc, countdown=min(30, 2 ** int(self.request.retries or 0))) from exc


async def _process_event(connection_id: str, payload: dict[str, Any]) -> dict[str, str]:
    async with async_session_factory() as db:
        connection = await db.get(IntegrationConnection, UUID(connection_id))
        if connection is None:
            return {"status": "missing"}
        await record_hub_usage(
            db,
            connection=connection,
            metric="amocrm_webhook",
            quantity=1,
        )
        await db.commit()
    logger.info("amoCRM.event_processed | connection_id={id}", id=connection_id)
    _ = payload
    return {"status": "ok"}


async def _bind_webhooks(connection_id: str) -> dict[str, str]:
    async with async_session_factory() as db:
        connection = await db.get(IntegrationConnection, UUID(connection_id))
        if connection is None or connection.status != HubConnectionStatus.CONNECTED.value:
            return {"status": "skipped"}
        secrets = await secrets_from_connection_with_vault(db, connection)
        adapter = AmoCRMHubAdapter()
        async with httpx.AsyncClient(timeout=20.0) as http:
            await adapter.bind_event_handlers(
                secrets=secrets,
                http=http,
                connection_id=connection.id,
            )
    return {"status": "bound"}
