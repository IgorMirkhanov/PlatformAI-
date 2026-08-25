"""Provider HTTP adapter contract. Secrets never log; transport is injectable."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import httpx


@dataclass
class PlatformOAuthApp:
    provider: str
    client_id: str
    client_secret: str
    redirect_uri: str | None = None
    auth_base_url: str | None = None
    token_url: str | None = None


@dataclass
class TokenBundle:
    """Decrypted tenant secrets — never persist this object as-is."""

    access_token: str | None = None
    refresh_token: str | None = None
    api_key: str | None = None
    webhook_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None
    external_account_id: str | None = None

    def as_vault_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {**self.extra}
        if self.access_token:
            payload["access_token"] = self.access_token
        if self.refresh_token:
            payload["refresh_token"] = self.refresh_token
        if self.api_key:
            payload["api_key"] = self.api_key
        if self.webhook_url:
            payload["webhook_url"] = self.webhook_url
        if self.external_account_id:
            payload["external_account_id"] = self.external_account_id
        if self.expires_at is not None:
            payload["expires_at"] = self.expires_at.isoformat()
        return payload


class ProviderAdapter(Protocol):
    provider: str

    async def connect(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        payload: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> TokenBundle: ...

    async def refresh(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
    ) -> TokenBundle: ...

    async def request(
        self,
        *,
        connection_id: UUID,
        secrets: TokenBundle,
        method: str,
        url: str,
        http: httpx.AsyncClient,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response: ...
