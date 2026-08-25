from __future__ import annotations

import sys

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, task_prerun, worker_process_init, worker_ready
from loguru import logger

from app.config import settings

celery_app = Celery(
    "mp_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.webhook_tasks",
        "app.tasks.crm_tasks",
        "app.tasks.rag_tasks",
        "app.tasks.flow_tasks",
        "app.tasks.bot_tasks",
        "app.tasks.telegram_poll_task",
        "app.workers.crm_tasks",
        "app.workers.crm_webhook_tasks",
        "app.tasks.oauth_refresh_task",
        "app.tasks.integration_health_task",
        "app.tasks.bitrix24_tasks",
        "app.tasks.amocrm_tasks",
        "app.tasks.wazzup_tasks",
        "app.tasks.hub_queue_tasks",
        "app.tasks.process_message",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue=settings.CELERY_INBOUND_QUEUE,
    task_routes={
        "app.tasks.webhook_tasks.process_inbound_message_task": {
            "queue": settings.CELERY_INBOUND_QUEUE,
        },
        "app.tasks.flow_tasks.execute_flow_task": {
            "queue": settings.CELERY_INBOUND_QUEUE,
        },
        "app.tasks.rag_tasks.ingest_document_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.bot_tasks.generate_ai_response": {
            "queue": settings.CELERY_INBOUND_QUEUE,
        },
        "app.tasks.crm_tasks.process_crm_action_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.crm_tasks.capture_lead_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.crm_tasks.run_automation_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.crm_tasks.dispatch_webhook_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.workers.crm_tasks.process_crm_automation_action": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.workers.crm_tasks.capture_lead_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.workers.crm_tasks.run_automation_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.workers.crm_tasks.dispatch_webhook_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.bitrix24_tasks.process_bitrix24_event_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.bitrix24_tasks.bind_bitrix24_events_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.bitrix24_tasks.execute_bitrix_rest_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.amocrm_tasks.process_amocrm_event_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.amocrm_tasks.bind_amocrm_webhooks_task": {
            "queue": settings.CELERY_CRM_QUEUE,
        },
        "app.tasks.wazzup_tasks.process_wazzup_event_task": {
            "queue": settings.CELERY_INBOUND_QUEUE,
        },
        "app.tasks.hub_queue_tasks.process_hub_webhook_event": {
            "queue": settings.CELERY_HUB_INBOUND_QUEUE,
        },
        "app.tasks.hub_queue_tasks.execute_hub_adapter_action": {
            "queue": settings.CELERY_HUB_OUTBOUND_QUEUE,
        },
    },
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    beat_schedule={
        "refresh-expiring-oauth-tokens": {
            "task": "app.tasks.oauth_refresh_task.refresh_expiring_oauth_tokens",
            "schedule": 60.0,
        },
        "integration-hub-health-check": {
            "task": "app.tasks.integration_health_task.check_connected_integrations",
            "schedule": crontab(minute=0),
        },
    },
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=settings.CELERY_TASK_ALWAYS_EAGER,
)


@worker_process_init.connect
def configure_worker_logging(**_: object) -> None:
    """Apply loguru formatting inside Celery worker containers."""
    from app.core.crypto import validate_encryption_at_startup
    from app.core.telemetry import init_telemetry

    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<magenta>CeleryWorker</magenta> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )
    init_telemetry()
    validate_encryption_at_startup()
    # Ensure hybrid credential accessors are registered for decrypted token reads.
    import app.models.bot  # noqa: F401
    import app.models.integrations  # noqa: F401

    logger.info(
        "CeleryWorker.startup | inbound_queue={inbound} crm_queue={crm} broker={broker}",
        inbound=settings.CELERY_INBOUND_QUEUE,
        crm=settings.CELERY_CRM_QUEUE,
        broker=settings.CELERY_BROKER_URL,
    )


@worker_ready.connect
def _start_telegram_poller(**_: object) -> None:
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return
    try:
        from app.core.redis_client import get_redis_client
        from app.tasks.telegram_poll_task import poll_telegram_updates

        redis = get_redis_client()
        if redis.set("telegram:poller:armed", "1", nx=True, ex=30):
            poll_telegram_updates.apply_async()
            logger.info("CeleryWorker.telegram_poller_started")
    except Exception as exc:
        logger.warning("CeleryWorker.telegram_poller_skip | error={error}", error=str(exc))


@task_prerun.connect
def _celery_bind_sentry_task_context(
    task_id: str | None = None,
    task: object | None = None,
    **_: object,
) -> None:
    """Attach Celery ``task_id`` / task name to the active Sentry scope."""
    try:
        import sentry_sdk
    except ImportError:
        return

    task_name = getattr(task, "name", None) or getattr(getattr(task, "__class__", None), "__name__", None)
    with sentry_sdk.configure_scope() as scope:
        if task_id:
            scope.set_tag("task_id", str(task_id))
            scope.set_context("celery", {"task_id": str(task_id), "task_name": task_name})
        if task_name:
            scope.set_tag("celery_task", str(task_name))


@task_failure.connect
def _celery_log_task_failure(
    task_id: str | None = None,
    exception: BaseException | None = None,
    einfo: object | None = None,
    sender: object | None = None,
    **_: object,
) -> None:
    """Log full task failure traces; Sentry capture is handled by CeleryIntegration."""
    task_name = getattr(sender, "name", None) or "unknown"
    logger.exception(
        "Celery.task_failure | task={task} task_id={task_id} error={error}",
        task=task_name,
        task_id=task_id,
        error=str(exception) if exception is not None else None,
    )
    # Reinforce task_id on the active scope so the integration event is tagged.
    try:
        import sentry_sdk
    except ImportError:
        return
    with sentry_sdk.configure_scope() as scope:
        if task_id:
            scope.set_tag("task_id", str(task_id))
        scope.set_tag("celery_task", str(task_name))
        scope.set_context(
            "celery",
            {
                "task_id": str(task_id) if task_id else None,
                "task_name": task_name,
                "einfo": str(einfo) if einfo is not None else None,
            },
        )
