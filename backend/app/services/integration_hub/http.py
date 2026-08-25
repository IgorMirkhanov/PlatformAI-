"""Shared outbound HTTP for Integration Hub adapters (rate-limited per connection)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from app.services.integration_hub.rate_limit import acquire_connection_slot


async def hub_request(
    http: httpx.AsyncClient,
    *,
    connection_id: UUID | None,
    method: str,
    url: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> httpx.Response:
    if connection_id is not None:
        acquire_connection_slot(connection_id)
    response = await http.request(
        method.upper(),
        url,
        json=json_body,
        params=params,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response
