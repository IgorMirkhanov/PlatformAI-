"""Generic OAuth2 for Integration Hub (Bitrix24 + amoCRM share this flow)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import resolve_webhook_base_url, settings
from app.core.security import _jwt_secret
from app.models.core_models import Bot
from app.models.integration_hub import (
    HubConnectionStatus,
    IntegrationConnection,
    IntegrationOAuthApp,
    IntegrationProvider,
)
from app.services.encryption import decrypt
from app.services.integration_hub.adapters.bitrix24 import Bitrix24HubAdapter
from app.repositories.credentials_repository import CredentialsRepository
from app.services.integration_hub.oauth_apps import get_platform_oauth_app
from app.services.integration_hub.service import integration_hub_service
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle

OAUTH_PROVIDERS = frozenset({"amocrm", "kommo", "bitrix24"})
_STATE_TYP = "ihub_oauth"
_STATE_TTL = timedelta(minutes=10)


class OAuthFlowError(ValueError):
    """User-facing OAuth failure (missing app, bad state, exchange error)."""


def callback_url(provider: str) -> str:
    return f"{resolve_webhook_base_url()}/api/v1/integrations/{provider}/callback"


def frontend_result_url(*, provider: str, status: str, **query: str) -> str:
    base = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
    params = {"provider": provider, "status": status, **{k: v for k, v in query.items() if v}}
    return f"{base}/integrations/hub/oauth-result?{urlencode(params)}"


def sign_oauth_state(
    *,
    workspace_id: uuid.UUID,
    provider: str,
    agent_id: uuid.UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "typ": _STATE_TYP,
        "sub": str(workspace_id),
        "workspace_id": str(workspace_id),
        "provider": (provider or "").strip().lower(),
        "iat": int(now.timestamp()),
        "exp": int((now + _STATE_TTL).timestamp()),
    }
    if agent_id is not None:
        payload["agent_id"] = str(agent_id)
    if extra:
        payload["extra"] = extra
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_oauth_state(state: str) -> dict[str, Any]:
    if not state or not str(state).strip():
        raise OAuthFlowError("Missing OAuth state.")
    try:
        payload = jwt.decode(
            str(state).strip(),
            _jwt_secret(),
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OAuthFlowError("OAuth state expired. Start the connection again.") from exc
    except jwt.InvalidTokenError as exc:
        raise OAuthFlowError("Invalid OAuth state.") from exc
    if payload.get("typ") != _STATE_TYP:
        raise OAuthFlowError("Invalid OAuth state type.")
    return payload


def build_authorize_url(
    *,
    platform_app: PlatformOAuthApp,
    provider: str,
    state: str,
    extra: dict[str, Any] | None = None,
) -> str:
    key = (provider or "").strip().lower()
    extra = extra or {}
    redirect = platform_app.redirect_uri or callback_url(key if key != "kommo" else "amocrm")
    if key in {"amocrm", "kommo"}:
        host = str(extra.get("subdomain") or extra.get("base_domain") or "").strip()
        if not host:
            raise OAuthFlowError("Для amoCRM укажите subdomain.")
        host = host.replace("https://", "").replace("http://", "").rstrip("/")
        if not host.endswith(".amocrm.ru") and "." not in host:
            host = f"{host}.amocrm.ru"
        params = urlencode(
            {
                "client_id": platform_app.client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "state": state,
                "mode": "post_message",
            }
        )
        return f"https://{host}/oauth?{params}"
    if key == "bitrix24":
        from app.services.integration_hub.adapters.bitrix24 import Bitrix24HubAdapter

        domain = str(extra.get("domain") or extra.get("portal") or "").strip() or None
        return Bitrix24HubAdapter().authorize_url(
            client_id=platform_app.client_id,
            redirect_uri=redirect,
            state=state,
            domain=domain,
        )
    raise OAuthFlowError(f"Provider {provider} does not use OAuth2.")


def secrets_from_connection(connection: IntegrationConnection) -> TokenBundle:
    access = decrypt(connection.encrypted_access_token) if connection.encrypted_access_token else None
    refresh = decrypt(connection.encrypted_refresh_token) if connection.encrypted_refresh_token else None
    extra = dict(connection.config_json or {})
    return TokenBundle(
        access_token=access or None,
        refresh_token=refresh or None,
        extra=extra,
        expires_at=connection.oauth_expires_at,
        external_account_id=connection.external_account_id,
        webhook_url=str(extra.get("webhook_url") or "") or None,
    )


async def secrets_from_connection_with_vault(
    db: AsyncSession,
    connection: IntegrationConnection,
) -> TokenBundle:
    """Merge row tokens with the vault payload (application_token, webhook_url, endpoints)."""
    base = secrets_from_connection(connection)
    if connection.credential_id is None:
        return base
    from app.models.tenant_credentials import TenantCredential
    from app.services.crypto_service import decrypt_payload

    cred = await db.scalar(
        select(TenantCredential).where(TenantCredential.id == connection.credential_id)
    )
    if cred is None:
        return base
    payload = decrypt_payload(
        cred.encrypted_payload,
        cred.encryption_iv,
        cred.encryption_tag,
        key_version=int(cred.key_version),
    )
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
    extra.update({k: v for k, v in (connection.config_json or {}).items() if v not in (None, "")})
    return TokenBundle(
        access_token=base.access_token or payload.get("access_token"),
        refresh_token=base.refresh_token or payload.get("refresh_token"),
        api_key=payload.get("api_key") or base.api_key,
        webhook_url=payload.get("webhook_url") or base.webhook_url,
        extra=extra,
        expires_at=base.expires_at,
        external_account_id=base.external_account_id or payload.get("external_account_id"),
    )


async def start_authorize(
    db: AsyncSession,
    *,
    provider: str,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    extra: dict[str, Any] | None = None,
) -> str:
    key = (provider or "").strip().lower()
    if key not in OAUTH_PROVIDERS:
        raise OAuthFlowError("OAuth2 is only available for amoCRM and Bitrix24.")
    if agent_id is not None:
        bot = await db.scalar(select(Bot).where(Bot.id == agent_id))
        if bot is None or bot.organization_id != workspace_id:
            raise OAuthFlowError("Agent not found in this workspace.")
    platform_app = await get_platform_oauth_app(db, key)
    if platform_app is None or not platform_app.client_id or not platform_app.client_secret:
        if key == "bitrix24":
            raise OAuthFlowError(
                "Bitrix24 OAuth app is not configured (BITRIX_APP_ID). "
                "Use Incoming Webhook URL on the Bitrix24 card instead."
            )
        raise OAuthFlowError("Platform OAuth app is not configured for this provider.")
    # Canonical redirect must match the partner cabinet entry character-for-character.
    slug = "amocrm" if key == "kommo" else key
    canonical = callback_url(slug)
    configured = (platform_app.redirect_uri or "").strip()
    if configured and configured.rstrip("/") != canonical.rstrip("/"):
        logger.warning(
            "OAuth.redirect_uri_override | provider={provider} configured={configured} "
            "canonical={canonical}",
            provider=key,
            configured=configured,
            canonical=canonical,
        )
    platform_app.redirect_uri = canonical
    state = sign_oauth_state(
        workspace_id=workspace_id,
        provider=key,
        agent_id=agent_id,
        extra=extra,
    )
    return build_authorize_url(
        platform_app=platform_app,
        provider=key,
        state=state,
        extra=extra,
    )


async def handle_callback(
    db: AsyncSession,
    *,
    provider: str,
    code: str,
    state: str,
    http: httpx.AsyncClient | None = None,
) -> IntegrationConnection:
    key = (provider or "").strip().lower()
    claims = decode_oauth_state(state)
    if claims.get("provider") != key and not (key == "amocrm" and claims.get("provider") == "kommo"):
        raise OAuthFlowError("OAuth state provider mismatch.")
    workspace_id = uuid.UUID(str(claims["workspace_id"]))
    agent_raw = claims.get("agent_id")
    agent_id = uuid.UUID(str(agent_raw)) if agent_raw else None
    extra = claims.get("extra") if isinstance(claims.get("extra"), dict) else {}
    payload = {"code": code, "authorization_code": code, **extra}
    row = await integration_hub_service.connect(
        db,
        organization_id=workspace_id,
        bot_id=agent_id,
        provider=key,
        payload=payload,
        http=http,
    )
    provider_row = await db.scalar(
        select(IntegrationProvider).where(IntegrationProvider.slug == key)
    )
    if provider_row is not None:
        row.provider_id = provider_row.id
    oauth_app_row = await db.scalar(
        select(IntegrationOAuthApp).where(IntegrationOAuthApp.provider == key)
    )
    if oauth_app_row is not None:
        row.oauth_app_id = oauth_app_row.id
    row.status = HubConnectionStatus.CONNECTED.value
    row.last_error = None
    await db.flush()
    logger.info(
        "IntegrationHub.oauth_connected | provider={provider} connection_id={id}",
        provider=key,
        id=row.id,
    )
    return row


async def mark_connection_revoked(
    db: AsyncSession,
    connection: IntegrationConnection,
    *,
    reason: str | None = None,
) -> None:
    """Local revoke: clear tokens/vault, status=revoked (idempotent)."""
    credential_id = connection.credential_id
    connection.status = HubConnectionStatus.REVOKED.value
    connection.encrypted_access_token = None
    connection.encrypted_refresh_token = None
    connection.credential_id = None
    connection.oauth_expires_at = None
    connection.last_error = (reason or "")[:500] or None
    connection.updated_at = datetime.now(timezone.utc)
    if credential_id is not None:
        await CredentialsRepository(db).revoke(credential_id)
    await db.flush()


async def _remote_revoke_provider(
    *,
    connection: IntegrationConnection,
    secrets: TokenBundle | None,
    platform_app: PlatformOAuthApp | None,
    catalog_revoke_url: str | None,
    http: httpx.AsyncClient,
) -> None:
    """Best-effort remote revoke; never blocks local revoke on provider errors."""
    if secrets is None:
        return
    provider = (connection.provider or "").strip().lower()
    if provider == "bitrix24" and secrets.access_token:
        try:
            adapter = Bitrix24HubAdapter()
            await adapter.rest_call(
                secrets=secrets,
                http=http,
                connection_id=connection.id,
                method="app.uninstall",
                params={},
            )
            return
        except Exception as exc:
            logger.warning(
                "IntegrationHub.bitrix_app_uninstall_failed | connection_id={id} error={error}",
                id=connection.id,
                error=type(exc).__name__,
            )
    revoke_url = catalog_revoke_url
    if not revoke_url and platform_app and platform_app.token_url:
        revoke_url = platform_app.token_url.replace("/token/", "/revoke/")
    if secrets.access_token and revoke_url:
        try:
            await http.post(
                revoke_url,
                data={
                    "token": secrets.access_token,
                    "client_id": platform_app.client_id if platform_app else "",
                    "client_secret": platform_app.client_secret if platform_app else "",
                },
            )
        except Exception as exc:
            logger.warning(
                "IntegrationHub.revoke_failed | connection_id={id} error={error}",
                id=connection.id,
                error=type(exc).__name__,
            )


async def disconnect_connection(
    db: AsyncSession,
    connection: IntegrationConnection,
    *,
    http: httpx.AsyncClient | None = None,
) -> None:
    """Disconnect & revoke: remote cancel (when possible) + local token wipe → ``revoked``."""
    secrets = None
    try:
        if connection.encrypted_access_token or connection.encrypted_refresh_token or connection.credential_id:
            secrets = await secrets_from_connection_with_vault(db, connection)
    except Exception:
        logger.warning(
            "IntegrationHub.disconnect_decrypt_skipped | connection_id={id}",
            id=connection.id,
        )
        try:
            if connection.encrypted_access_token or connection.encrypted_refresh_token:
                secrets = secrets_from_connection(connection)
        except Exception:
            secrets = None

    platform_app = await get_platform_oauth_app(db, connection.provider)
    catalog = await db.scalar(
        select(IntegrationProvider).where(IntegrationProvider.slug == connection.provider)
    )
    catalog_revoke = catalog.revoke_url if catalog else None

    client = http or httpx.AsyncClient(timeout=15.0)
    close = http is None
    try:
        await _remote_revoke_provider(
            connection=connection,
            secrets=secrets,
            platform_app=platform_app,
            catalog_revoke_url=catalog_revoke,
            http=client,
        )
    finally:
        if close:
            await client.aclose()

    await mark_connection_revoked(db, connection, reason=None)
    logger.info(
        "IntegrationHub.disconnected | connection_id={id} provider={provider}",
        id=connection.id,
        provider=connection.provider,
    )
