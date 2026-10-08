"""Generic OAuth2 for Integration Hub (Bitrix24 + amoCRM share this flow)."""

from __future__ import annotations

import asyncio
import hashlib
import json
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
from app.services.encryption import decrypt, encrypt
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


def secrets_url(provider: str) -> str:
    """amoCRM posts client_id and client_secret here before the browser redirect."""
    return f"{resolve_webhook_base_url()}/api/v1/integrations/{provider}/secrets"


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
        # Account is chosen on amo's side. mode=popup returns to our redirect URI
        # with code + referer. mode=post_message never hits the callback.
        picker = "https://www.kommo.com/oauth" if key == "kommo" else "https://www.amocrm.ru/oauth"
        params = urlencode(
            {
                "client_id": platform_app.client_id,
                "state": state,
                "mode": "popup",
            }
        )
        return f"{picker}?{params}"
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


def build_external_authorize_url(*, provider: str, state: str) -> str:
    """Account picker that creates an amo integration at click time.

    No platform client_id is required. amo sends the new integration's
    client_id and client_secret to secrets_uri, then redirects with the code.
    """
    key = (provider or "").strip().lower()
    picker = "https://www.kommo.com/oauth/" if key == "kommo" else "https://www.amocrm.ru/oauth/"
    slug = "amocrm" if key == "kommo" else key
    origin = (settings.FRONTEND_URL or resolve_webhook_base_url()).rstrip("/")
    if not origin.startswith("https://"):
        origin = resolve_webhook_base_url()
    params = [
        ("state", state),
        ("mode", "post_message"),
        ("origin", origin),
        ("name", "MP.AI"),
        ("description", "Подключение CRM к агенту MP.AI"),
        ("redirect_uri", callback_url(slug)),
        ("secrets_uri", secrets_url(slug)),
        ("logo", f"{resolve_webhook_base_url()}/amocrm-logo.png"),
        ("scopes[]", "crm"),
        ("scopes[]", "notifications"),
    ]
    return f"{picker}?{urlencode(params)}"


_INSTALL_PREFIX = "amocrm:oauth_install:"


def _install_key(state: str) -> str:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return f"{_INSTALL_PREFIX}{digest}"


def save_install_secrets(state: str, client_id: str, client_secret: str) -> None:
    decode_oauth_state(state)
    from app.core.redis_client import get_redis_client

    payload = json.dumps(
        {"client_id": client_id, "client_secret": encrypt(client_secret)},
        separators=(",", ":"),
    )
    get_redis_client().setex(_install_key(state), int(_STATE_TTL.total_seconds()), payload)


def load_install_secrets(state: str) -> dict[str, str] | None:
    from app.core.redis_client import get_redis_client

    raw = get_redis_client().get(_install_key(state))
    if not raw:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    client_id = str(data.get("client_id") or "").strip()
    sealed = str(data.get("client_secret") or "").strip()
    if not client_id or not sealed:
        return None
    return {"client_id": client_id, "client_secret": decrypt(sealed)}


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
    if key in {"amocrm", "kommo"} and (
        platform_app is None or not platform_app.client_id or not platform_app.client_secret
    ):
        state = sign_oauth_state(
            workspace_id=workspace_id,
            provider=key,
            agent_id=agent_id,
            extra=extra,
        )
        return build_external_authorize_url(provider=key, state=state)
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


def account_from_referer(referer: str | None, provider: str) -> str:
    """amoCRM/Kommo send the chosen account host as `referer` on the redirect."""
    host = (referer or "").strip()
    host = host.replace("https://", "").replace("http://", "").split("/")[0].split("?")[0]
    if not host:
        return ""
    key = (provider or "").strip().lower()
    if "." not in host:
        host = f"{host}.kommo.com" if key == "kommo" else f"{host}.amocrm.ru"
    return host


async def mirror_amocrm_tokens_to_bot(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    connection: IntegrationConnection,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> None:
    """Deals read bot.credentials.crm.amocrm. Copy the hub OAuth result there."""
    bot = await db.scalar(select(Bot).where(Bot.id == bot_id))
    if bot is None:
        return
    platform_app = await get_platform_oauth_app(db, "amocrm")
    secrets = secrets_from_connection(connection)
    domain = str(secrets.extra.get("subdomain") or secrets.external_account_id or "").strip()
    resolved_id = (client_id or (platform_app.client_id if platform_app else "") or "").strip()
    resolved_secret = (
        client_secret or (platform_app.client_secret if platform_app else "") or ""
    ).strip()
    if (
        not resolved_id
        or not resolved_secret
        or not domain
        or not secrets.access_token
        or not secrets.refresh_token
    ):
        logger.warning(
            "IntegrationHub.amocrm_bot_mirror_skipped | bot_id={bot_id} has_domain={has_domain}",
            bot_id=bot_id,
            has_domain=bool(domain),
        )
        return
    expires_in = 86400
    if connection.oauth_expires_at is not None:
        expires = connection.oauth_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        expires_in = max(60, int((expires - datetime.now(timezone.utc)).total_seconds()))
    from app.services.crm_orchestrator import crm_orchestrator

    await crm_orchestrator._persist_amocrm_tokens(
        db,
        bot,
        domain=domain,
        client_id=resolved_id,
        client_secret=resolved_secret,
        token_data={
            "access_token": secrets.access_token,
            "refresh_token": secrets.refresh_token,
            "expires_in": expires_in,
        },
        redirect_uri=(platform_app.redirect_uri if platform_app else None) or callback_url("amocrm"),
    )


async def handle_callback(
    db: AsyncSession,
    *,
    provider: str,
    code: str,
    state: str,
    referer: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> IntegrationConnection:
    key = (provider or "").strip().lower()
    claims = decode_oauth_state(state)
    if claims.get("provider") != key and not (key == "amocrm" and claims.get("provider") == "kommo"):
        raise OAuthFlowError("OAuth state provider mismatch.")
    workspace_id = uuid.UUID(str(claims["workspace_id"]))
    agent_raw = claims.get("agent_id")
    agent_id = uuid.UUID(str(agent_raw)) if agent_raw else None
    extra = dict(claims.get("extra") or {}) if isinstance(claims.get("extra"), dict) else {}
    if key in {"amocrm", "kommo"}:
        account = account_from_referer(referer, key) or account_from_referer(
            str(extra.get("subdomain") or extra.get("base_domain") or ""),
            key,
        )
        if not account:
            raise OAuthFlowError("amoCRM не вернул выбранный аккаунт. Начните подключение заново.")
        extra["subdomain"] = account
        extra["base_domain"] = account
    install: dict[str, str] | None = None
    if key in {"amocrm", "kommo"}:
        install = load_install_secrets(state)
        if install is None:
            platform_app = await get_platform_oauth_app(db, key)
            needs_install = (
                platform_app is None
                or not platform_app.client_id
                or not platform_app.client_secret
            )
            if needs_install:
                for _attempt in range(8):
                    await asyncio.sleep(0.25)
                    install = load_install_secrets(state)
                    if install:
                        break
                if install is None:
                    raise OAuthFlowError(
                        "amoCRM не прислал ключи интеграции. Начните подключение заново."
                    )
    payload = {"code": code, "authorization_code": code, **extra}
    if install:
        payload["client_id"] = install["client_id"]
        payload["client_secret"] = install["client_secret"]
        payload["redirect_uri"] = callback_url("amocrm")
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
    if agent_id is not None and key in {"amocrm", "kommo"}:
        await mirror_amocrm_tokens_to_bot(
            db,
            bot_id=agent_id,
            connection=row,
            client_id=str(payload.get("client_id") or "") or None,
            client_secret=str(payload.get("client_secret") or "") or None,
        )
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
