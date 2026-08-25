"""Platform OAuth app (one per provider) — ENV is source of truth, DB is optional overlay."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.integration_hub import IntegrationOAuthApp
from app.models.tenant_credentials import CredentialKind
from app.services.crypto_service import decrypt_field, encrypt_field
from app.services.integration_hub.types import PlatformOAuthApp

_KIND_TO_CREDENTIAL = {
    "amocrm": CredentialKind.CRM_AMOCRM.value,
    "kommo": CredentialKind.CRM_AMOCRM.value,
    "bitrix24": CredentialKind.CRM_BITRIX24.value,
    "wazzup": CredentialKind.CHANNEL_WAZZUP.value,
    "whatsapp": CredentialKind.CHANNEL_GREENAPI.value,
    "greenapi": CredentialKind.CHANNEL_GREENAPI.value,
    "kaspi_pay": CredentialKind.KASPI_PAY.value,
}


def credential_kind_for_provider(provider: str) -> str:
    key = (provider or "").strip().lower()
    return _KIND_TO_CREDENTIAL.get(key, f"hub_{key}")


def _from_settings(provider: str) -> PlatformOAuthApp | None:
    key = (provider or "").strip().lower()
    if key in {"amocrm", "kommo"}:
        client_id = (settings.AMOCRM_CLIENT_ID or "").strip()
        secret = (settings.AMOCRM_CLIENT_SECRET or "").strip()
        if not client_id:
            return None
        return PlatformOAuthApp(
            provider="amocrm",
            client_id=client_id,
            client_secret=secret,
            redirect_uri=(settings.AMOCRM_REDIRECT_URI or "").strip() or None,
        )
    if key == "bitrix24":
        client_id = (settings.BITRIX_APP_ID or "").strip()
        secret = (settings.BITRIX_APP_SECRET or "").strip()
        if not client_id:
            return None
        return PlatformOAuthApp(
            provider="bitrix24",
            client_id=client_id,
            client_secret=secret,
            auth_base_url="https://oauth.bitrix.info/oauth/authorize/",
            token_url="https://oauth.bitrix.info/oauth/token/",
        )
    return None


async def get_platform_oauth_app(db: AsyncSession, provider: str) -> PlatformOAuthApp | None:
    """ENV wins (one platform app). DB overlay is only used when ENV client_id is unset."""
    env_app = _from_settings(provider)
    if env_app is not None:
        return env_app

    key = (provider or "").strip().lower()
    if key == "kommo":
        key = "amocrm"
    row = await db.scalar(
        select(IntegrationOAuthApp).where(
            IntegrationOAuthApp.provider == key,
            IntegrationOAuthApp.is_enabled.is_(True),
        )
    )
    if row is None:
        return None
    secret = decrypt_field(row.encrypted_client_secret) if row.encrypted_client_secret else ""
    return PlatformOAuthApp(
        provider=row.provider,
        client_id=row.client_id,
        client_secret=secret,
        redirect_uri=row.redirect_uri,
        auth_base_url=row.auth_base_url,
        token_url=row.token_url,
    )


async def upsert_platform_oauth_app_from_env(db: AsyncSession, provider: str) -> None:
    """Persist ENV client_id (secret envelope-encrypted) so ops can inspect without reading env."""
    app = _from_settings(provider)
    if app is None or not app.client_id:
        return
    key = "amocrm" if provider in {"amocrm", "kommo"} else provider
    row = await db.scalar(select(IntegrationOAuthApp).where(IntegrationOAuthApp.provider == key))
    encrypted = encrypt_field(app.client_secret) if app.client_secret else None
    if row is None:
        db.add(
            IntegrationOAuthApp(
                provider=key,
                client_id=app.client_id,
                encrypted_client_secret=encrypted,
                redirect_uri=app.redirect_uri,
                token_url=app.token_url,
            )
        )
    else:
        row.client_id = app.client_id
        row.encrypted_client_secret = encrypted
        row.redirect_uri = app.redirect_uri
        row.token_url = app.token_url
    await db.flush()
