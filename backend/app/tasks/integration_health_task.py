"""Hourly Integration Hub health-check — testConnection per connected row."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.database import async_session_factory, run_celery_async
from app.models.core_models import SystemNotification, SystemNotificationCategory, SystemNotificationSeverity
from app.models.integration_hub import HubConnectionStatus, IntegrationConnection
from app.services.integration_hub.crm_adapter import AuthExpiredError, get_crm_adapter


@celery_app.task(name="app.tasks.integration_health_task.check_connected_integrations")
def check_connected_integrations() -> dict[str, int]:
    return run_celery_async(_check_connected_integrations())


async def _check_connected_integrations() -> dict[str, int]:
    scanned = 0
    healthy = 0
    expired = 0
    errors = 0
    async with async_session_factory() as db:
        rows = list(
            (
                await db.scalars(
                    select(IntegrationConnection).where(
                        IntegrationConnection.status == HubConnectionStatus.CONNECTED.value
                    )
                )
            ).all()
        )
        for connection in rows:
            scanned += 1
            adapter = get_crm_adapter(connection.provider)
            if adapter is None:
                connection.last_health_check_at = datetime.now(timezone.utc)
                healthy += 1
                continue
            try:
                from app.services.integration_hub.oauth import secrets_from_connection_with_vault

                secrets = await secrets_from_connection_with_vault(db, connection)
            except Exception:
                logger.warning(
                    "IntegrationHealth.decrypt_failed | connection_id={id}",
                    id=connection.id,
                )
                errors += 1
                continue
            try:
                async with httpx.AsyncClient(timeout=15.0) as http:
                    ok = await adapter.test_connection(
                        secrets=secrets, http=http, connection_id=connection.id
                    )
                if ok:
                    connection.last_health_check_at = datetime.now(timezone.utc)
                    connection.last_error = None
                    healthy += 1
                else:
                    raise AuthExpiredError("test_connection returned false")
            except AuthExpiredError:
                connection.status = HubConnectionStatus.EXPIRED.value
                connection.last_error = "authorization_expired"
                connection.last_health_check_at = datetime.now(timezone.utc)
                connection.updated_at = datetime.now(timezone.utc)
                expired += 1
                db.add(
                    SystemNotification(
                        organization_id=connection.organization_id,
                        category=SystemNotificationCategory.SYSTEM,
                        severity=SystemNotificationSeverity.WARNING,
                        title="Интеграция требует повторного входа",
                        message=(
                            f"Подключение {connection.provider} истекло. "
                            "Откройте Integrations и подключите сервис заново."
                        ),
                        reference_id=str(connection.id),
                        is_read=False,
                    )
                )
                logger.info(
                    "IntegrationHealth.expired | connection_id={id} provider={provider}",
                    id=connection.id,
                    provider=connection.provider,
                )
            except Exception as exc:
                connection.last_error = type(exc).__name__
                connection.last_health_check_at = datetime.now(timezone.utc)
                errors += 1
                logger.warning(
                    "IntegrationHealth.failed | connection_id={id} error={error}",
                    id=connection.id,
                    error=type(exc).__name__,
                )
        await db.commit()
    return {"scanned": scanned, "healthy": healthy, "expired": expired, "errors": errors}
