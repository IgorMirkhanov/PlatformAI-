"""Celery worker for partner CRM webhook delivery (crm_actions queue)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Coroutine

from loguru import logger

from app.core.celery_app import celery_app
from app.core.database import async_session_factory, run_celery_async


def _run_sync(coro: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any] | None:
    """
    Drive ``coro`` to completion from sync code — nobody reads this task's
    return value (``enqueue_partner_webhook`` only checks that ``apply_async``
    didn't raise), so both branches below are safe.

    A real Celery prefork worker has no event loop of its own, so
    ``run_celery_async`` (reused loop, like the Telegram/GreenAPI pollers) is
    the normal path. But this task can also run eagerly
    (``CELERY_TASK_ALWAYS_EAGER``) from *inside* an already-running loop —
    e.g. a CRM contact/deal created during a live async request, or in an
    async test. Neither ``asyncio.run`` nor a second ``run_until_complete``
    on this thread is allowed then, and driving the coroutine from a second
    thread doesn't work either — ``async_session_factory``'s engine is bound
    to the original loop, so a connection opened from another thread's loop
    conflicts across loops. So when a loop is already running, genuinely
    fire-and-forget: schedule the coroutine on that same loop and return
    immediately, matching this task's own "fire-and-forget" contract instead
    of fighting asyncio's single-loop-per-thread rule.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run_celery_async(coro)
    def _log_if_failed(task: "asyncio.Task[dict[str, Any]]") -> None:
        exc = task.exception()
        if exc is not None:
            logger.error(
                "CRM.dispatch_webhook_background_failed | error={error}",
                error=f"{type(exc).__name__}: {exc}",
            )

    task = asyncio.ensure_future(coro)
    task.add_done_callback(_log_if_failed)
    return None


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
) -> dict[str, Any] | None:
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
        return _run_sync(
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
