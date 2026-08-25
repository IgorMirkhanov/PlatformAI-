"""Integration Hub service — connect / disconnect / atomic token refresh."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pg_locks import (
    LOCK_NS_CRM_OAUTH,
    pg_advisory_xact_lock_hashtext,
    pg_advisory_xact_lock_uuid,
)
from app.models.integration_hub import HubConnectionStatus, IntegrationConnection
from app.models.tenant_credentials import CredentialStatus
from app.repositories.credentials_repository import CredentialsRepository
from app.services.crypto_service import decrypt_payload
from app.services.encryption import encrypt
from app.services.integration_hub.adapters import get_hub_adapter
from app.services.integration_hub.oauth_apps import credential_kind_for_provider, get_platform_oauth_app
from app.services.integration_hub.types import TokenBundle

_OAUTH_PROVIDERS = frozenset({"amocrm", "kommo", "bitrix24"})


def _bundle_from_vault(payload: dict[str, Any]) -> TokenBundle:
    expires_raw = payload.get("expires_at")
    expires_at = None
    if isinstance(expires_raw, str) and expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
        except ValueError:
            expires_at = None
    extra = {
        k: v
        for k, v in payload.items()
        if k
        not in {
            "access_token",
            "refresh_token",
            "api_key",
            "webhook_url",
            "external_account_id",
            "expires_at",
        }
    }
    return TokenBundle(
        access_token=payload.get("access_token"),
        refresh_token=payload.get("refresh_token"),
        api_key=payload.get("api_key"),
        webhook_url=payload.get("webhook_url"),
        extra=extra,
        expires_at=expires_at,
        external_account_id=payload.get("external_account_id"),
    )


class IntegrationHubService:
    async def list_connections(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        bot_id: uuid.UUID | None = None,
    ) -> list[IntegrationConnection]:
        stmt = select(IntegrationConnection).where(
            IntegrationConnection.organization_id == organization_id
        )
        if bot_id is not None:
            stmt = stmt.where(IntegrationConnection.bot_id == bot_id)
        return list((await db.scalars(stmt)).all())

    async def connect(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        bot_id: uuid.UUID | None,
        provider: str,
        payload: dict[str, Any],
        http: httpx.AsyncClient | None = None,
    ) -> IntegrationConnection:
        key = (provider or "").strip().lower()
        adapter = get_hub_adapter(key)
        platform_app = await get_platform_oauth_app(db, key)
        client = http or httpx.AsyncClient(timeout=20.0)
        close = http is None
        try:
            bundle = await adapter.connect(platform_app=platform_app, payload=payload, http=client)

            creds = CredentialsRepository(db)
            kind = credential_kind_for_provider(key)
            label = f"hub:{key}:{bot_id or 'org'}"
            credential = await creds.upsert(
                organization_id=organization_id,
                kind=kind,
                payload=bundle.as_vault_payload(),
                label=label,
                oauth_expires_at=bundle.expires_at,
            )

            conditions = [
                IntegrationConnection.organization_id == organization_id,
                IntegrationConnection.provider == key,
            ]
            if bot_id is None:
                conditions.append(IntegrationConnection.bot_id.is_(None))
            else:
                conditions.append(IntegrationConnection.bot_id == bot_id)
            row = await db.scalar(select(IntegrationConnection).where(*conditions))
            public_config = {
                k: v
                for k, v in payload.items()
                if k
                not in {
                    "client_secret",
                    "authorization_code",
                    "code",
                    "access_token",
                    "refresh_token",
                    "api_key",
                    "api_token",
                    "merchant_token",
                    "webhook_url",
                    "token",
                    "application_token",
                    "secret_key",
                    "webhook_secret",
                    "client_access_token",
                }
            }
            for public_key in (
                "domain",
                "member_id",
                "client_endpoint",
                "status",
                "auth_mode",
                "subdomain",
                "account_id",
                "channels",
                "metadata",
                "webhook_uri",
                "webhook_registered",
                "channel_id",
            ):
                if bundle.extra.get(public_key):
                    public_config[public_key] = bundle.extra[public_key]
            if row is None:
                row = IntegrationConnection(
                    organization_id=organization_id,
                    bot_id=bot_id,
                    provider=key,
                    status=HubConnectionStatus.CONNECTED.value,
                    credential_id=credential.id,
                    external_account_id=bundle.external_account_id,
                    config_json=public_config,
                    oauth_expires_at=bundle.expires_at,
                )
                db.add(row)
            else:
                # Re-connect after revoke/expired: same row, clean connected cycle.
                row.status = HubConnectionStatus.CONNECTED.value
                row.credential_id = credential.id
                row.external_account_id = bundle.external_account_id
                row.config_json = public_config
                row.oauth_expires_at = bundle.expires_at
                row.last_error = None
                row.updated_at = datetime.now(timezone.utc)
            _seal_tokens(row, bundle)
            await db.flush()
            binder = getattr(adapter, "bind_event_handlers", None)
            if callable(binder) and key == "bitrix24":
                from app.config import settings
                from app.tasks.bitrix24_tasks import bind_bitrix24_events_task

                bind_bitrix24_events_task.apply_async(
                    args=[str(row.id), 0],
                    queue=settings.CELERY_CRM_QUEUE,
                )
            elif callable(binder) and key == "wazzup":
                try:
                    uri = await binder(secrets=bundle, http=client, connection_id=row.id)
                    cfg = dict(row.config_json or {})
                    cfg["webhook_registered"] = True
                    if uri:
                        cfg["webhook_uri"] = uri
                    if bundle.extra.get("metadata"):
                        cfg["metadata"] = bundle.extra["metadata"]
                    if bundle.extra.get("channels"):
                        cfg["channels"] = bundle.extra["channels"]
                    row.config_json = cfg
                except Exception:
                    row.last_error = "event_bind_failed"
            elif callable(binder) and key in {"amocrm", "kommo"}:
                from app.config import settings
                from app.tasks.amocrm_tasks import bind_amocrm_webhooks_task

                bind_amocrm_webhooks_task.apply_async(
                    args=[str(row.id)],
                    queue=settings.CELERY_CRM_QUEUE,
                )
            elif callable(binder):
                try:
                    uri = await binder(secrets=bundle, http=client, connection_id=row.id)
                    if uri:
                        cfg = dict(row.config_json or {})
                        cfg["webhook_registered"] = True
                        cfg["webhook_uri"] = uri
                        row.config_json = cfg
                except Exception:
                    row.last_error = "event_bind_failed"
            return row
        finally:
            if close:
                await client.aclose()

    async def disconnect(self, db: AsyncSession, connection: IntegrationConnection) -> None:
        from app.services.integration_hub.oauth import disconnect_connection

        await disconnect_connection(db, connection)

    async def refresh_connection(
        self,
        db: AsyncSession,
        connection: IntegrationConnection,
        *,
        http: httpx.AsyncClient | None = None,
        expected_refresh_token: str | None = None,
    ) -> IntegrationConnection:
        """Atomic refresh: hashtext advisory lock + SELECT FOR UPDATE.

        amoCRM refresh_token is one-time. Two parallel callers with the same
        token would permanently lose OAuth. Waiters re-read vault after the
        lock and skip HTTP if the token already rotated.
        """
        await pg_advisory_xact_lock_hashtext(db, str(connection.id))
        await pg_advisory_xact_lock_uuid(db, LOCK_NS_CRM_OAUTH, connection.id)
        locked = await db.scalar(
            select(IntegrationConnection)
            .where(IntegrationConnection.id == connection.id)
            .with_for_update()
        )
        if locked is None:
            raise ValueError("Connection disappeared under lock.")
        if locked.credential_id is None:
            raise ValueError("Connection has no vault credential.")

        from app.models.tenant_credentials import TenantCredential

        cred_row = await db.scalar(
            select(TenantCredential)
            .where(TenantCredential.id == locked.credential_id)
            .with_for_update()
        )
        if cred_row is None:
            raise ValueError("Vault credential missing.")
        secrets = _bundle_from_vault(
            decrypt_payload(
                cred_row.encrypted_payload,
                cred_row.encryption_iv,
                cred_row.encryption_tag,
                key_version=int(cred_row.key_version),
            )
        )
        if (
            expected_refresh_token
            and secrets.refresh_token
            and secrets.refresh_token != expected_refresh_token
        ):
            return locked
        if (
            expected_refresh_token is None
            and locked.provider in {"amocrm", "kommo"}
            and locked.oauth_expires_at is not None
            and locked.oauth_expires_at > datetime.now(timezone.utc) + timedelta(minutes=5)
        ):
            return locked

        adapter = get_hub_adapter(locked.provider)
        platform_app = await get_platform_oauth_app(db, locked.provider)
        client = http or httpx.AsyncClient(timeout=20.0)
        close = http is None
        try:
            bundle = await adapter.refresh(platform_app=platform_app, secrets=secrets, http=client)
        finally:
            if close:
                await client.aclose()

        creds = CredentialsRepository(db)
        await creds.upsert(
            organization_id=locked.organization_id,
            kind=cred_row.kind,
            payload=bundle.as_vault_payload(),
            label=cred_row.label,
            oauth_expires_at=bundle.expires_at,
            status=CredentialStatus.ACTIVE.value,
        )
        locked.oauth_expires_at = bundle.expires_at
        locked.status = HubConnectionStatus.CONNECTED.value
        locked.last_error = None
        locked.updated_at = datetime.now(timezone.utc)
        _seal_tokens(locked, bundle)
        await db.flush()
        return locked


def _seal_tokens(connection: IntegrationConnection, bundle: TokenBundle) -> None:
    if bundle.access_token:
        connection.encrypted_access_token = encrypt(bundle.access_token)
    if bundle.refresh_token:
        connection.encrypted_refresh_token = encrypt(bundle.refresh_token)


integration_hub_service = IntegrationHubService()
