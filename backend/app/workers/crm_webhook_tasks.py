"""Celery worker for partner CRM webhook delivery (crm_actions queue)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger

from app.core.celery_app import celery_app
from app.core.database import async_session_factory


async def _dispatch_webhook_async(
    organization_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from app.services.crm.webhook_dispatcher_service import webhook_dispatcher_service

    async with async_session_factory() as db:
        try:
            results = await webhook_dispatcher_service.dispatch_event(
                db,
                organization_id,
                event_type,
                payload,
            )
            return {
                "success": True,
                "organization_id": str(organization_id),
                "event_type": event_type,
                "deliveries": results,
            }
        except Exception:
            await db.rollback()
            raise


@celery_app.task(
    bind=True,
    name="app.tasks.crm_tasks.dispatch_webhook_task",
    max_retries=3,
    soft_time_limit=60,
)
def dispatch_webhook_task(
    self,
    organization_id_str: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deliver partner CRM webhooks on the ``crm_actions`` queue."""
    from app.config import settings

    logger.info(
        "CRM.dispatch_webhook_task | task_id={task_id} org={org} event={event} queue={queue}",
        task_id=self.request.id,
        org=organization_id_str,
        event=event_type,
        queue=settings.CELERY_CRM_QUEUE,
    )
    try:
        return asyncio.run(
            _dispatch_webhook_async(
                uuid.UUID(organization_id_str),
                event_type,
                payload or {},
            )
        )
    except Exception as exc:
        logger.exception(
            "CRM.dispatch_webhook_failed | org={org} event={event} error={error}",
            org=organization_id_str,
            event=event_type,
            error=str(exc),
        )
        raise
