"""WhatsApp hub adapter — MVP routes WhatsApp exclusively through Wazzup.

Direct Meta Cloud API / Green API connections are not offered at this stage.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.services.integration_hub.http import hub_request
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle

_WAZZUP_ONLY = (
    "WhatsApp в MVP подключается только через Wazzup (API-ключ). "
    "Прямая интеграция Meta Cloud API отключена на этом этапе."
)


class WhatsAppHubAdapter:
    provider = "whatsapp"

    async def connect(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        payload: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        _ = platform_app, payload, http
        raise ValueError(_WAZZUP_ONLY)

    async def refresh(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        _ = platform_app, http
        return secrets

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
    ) -> httpx.Response:
        _ = secrets
        return await hub_request(
            http,
            connection_id=connection_id,
            method=method,
            url=url,
            json_body=json_body,
            params=params,
        )
