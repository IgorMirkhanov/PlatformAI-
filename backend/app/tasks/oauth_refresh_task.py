"""Celery beat: refresh amoCRM / Bitrix OAuth credentials under PG advisory lock."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select, text

from app.core.celery_app import celery_app
from app.core.database import async_session_factory, run_celery_async
from app.core.metrics import record_oauth_refresh
from app.core.pg_locks import advisory_unlock, lock_key_for_credential, try_advisory_lock
from app.models.integration_hub import HubConnectionStatus, IntegrationConnection
from app.models.tenant_credentials import CredentialKind, CredentialStatus, TenantCredential


@celery_app.task(name="app.tasks.oauth_refresh_task.refresh_expiring_oauth_tokens")
def refresh_expiring_oauth_tokens() -> dict[str, int]:
    return run_celery_async(_refresh_expiring_oauth_tokens())


async def _refresh_expiring_oauth_tokens() -> dict[str, int]:
    scanned = 0
    refreshed = 0
    skipped = 0
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=5)
    async with async_session_factory() as db:
        hub_ids = list(
            (
                await db.scalars(
                    select(IntegrationConnection.id).where(
                        IntegrationConnection.status == HubConnectionStatus.CONNECTED.value,
                        IntegrationConnection.oauth_expires_at.is_not(None),
                        IntegrationConnection.oauth_expires_at <= cutoff,
                        IntegrationConnection.credential_id.is_not(None),
                    )
                )
            ).all()
        )
        linked_credential_ids = set(
            (
                await db.scalars(
                    select(IntegrationConnection.credential_id).where(
                        IntegrationConnection.credential_id.is_not(None)
                    )
                )
            ).all()
        )
        from app.services.integration_hub.service import integration_hub_service

        for connection_id in hub_ids:
            scanned += 1
            connection = await db.get(IntegrationConnection, connection_id)
            if connection is None:
                skipped += 1
                continue
            try:
                await integration_hub_service.refresh_connection(db, connection)
                refreshed += 1
                record_oauth_refresh(connection.provider, "ok")
            except Exception as exc:
                connection.status = HubConnectionStatus.ERROR.value
                connection.last_error = str(exc)[:2000]
                record_oauth_refresh(connection.provider, "error")
                logger.warning(
                    "OAuthRefresh.hub_failed | connection_id={id} error={error}",
                    id=connection.id,
                    error=str(exc),
                )

        stmt = select(TenantCredential).where(
            TenantCredential.kind.in_(
                [CredentialKind.CRM_AMOCRM.value, CredentialKind.CRM_BITRIX24.value]
            ),
            TenantCredential.status == CredentialStatus.ACTIVE.value,
            TenantCredential.oauth_expires_at.is_not(None),
            TenantCredential.oauth_expires_at <= cutoff,
        )
        if linked_credential_ids:
            stmt = stmt.where(TenantCredential.id.notin_(linked_credential_ids))
        rows = list((await db.scalars(stmt)).all())
        for row in rows:
            scanned += 1
            lock_key = lock_key_for_credential(row.id)
            locked = await try_advisory_lock(db, lock_key)
            if not locked:
                skipped += 1
                continue
            try:
                row.oauth_refresh_locked_until = datetime.now(timezone.utc) + timedelta(minutes=2)
                await db.flush()
                from app.services.crm_orchestrator import crm_orchestrator

                if row.kind == CredentialKind.CRM_AMOCRM.value and hasattr(
                    crm_orchestrator, "refresh_credential_row"
                ):
                    await crm_orchestrator.refresh_credential_row(db, row)
                    refreshed += 1
                    record_oauth_refresh(row.kind, "ok")
                else:
                    skipped += 1
                    record_oauth_refresh(row.kind, "skipped")
            except Exception as exc:
                row.status = CredentialStatus.ERROR.value
                row.last_error = str(exc)[:2000]
                record_oauth_refresh(row.kind, "error")
                logger.warning(
                    "OAuthRefresh.failed | credential_id={id} error={error}",
                    id=row.id,
                    error=str(exc),
                )
            finally:
                await advisory_unlock(db, lock_key)
                row.oauth_refresh_locked_until = None
        await db.commit()
    return {"scanned": scanned, "refreshed": refreshed, "skipped": skipped}


async def _try_lock(db, credential_id: uuid.UUID) -> bool:
    result = await db.execute(
        text("SELECT pg_try_advisory_lock(hashtext(:key))"),
        {"key": str(credential_id)},
    )
    value = result.scalar()
    return bool(value)


async def _unlock(db, credential_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT pg_advisory_unlock(hashtext(:key))"),
        {"key": str(credential_id)},
    )
