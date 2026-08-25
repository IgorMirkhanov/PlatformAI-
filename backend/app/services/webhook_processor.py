"""Shared inbound webhook processor for Integration Hub providers.

Checklist §3: Redis+DB dedup by external_event_id; workspace mismatch → dead_letter.
Provider-specific verify/parse stays in bitrix/amocrm/wazzup/kaspi modules;
they call ``process_hub_inbound_event`` after auth.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_hub import IntegrationConnection
from app.services.integration_hub.webhook_dedup import (
    InboundAcceptResult,
    accept_inbound_webhook,
    enqueue_if_needed,
)


async def process_hub_inbound_event(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    provider: str,
    external_event_id: str,
    payload: dict[str, Any],
) -> InboundAcceptResult:
    """Accept one provider event (dedup / dead_letter). Caller commits then enqueue_if_needed."""
    return await accept_inbound_webhook(
        db,
        connection=connection,
        provider=provider,
        external_event_id=external_event_id,
        payload=payload,
    )


# Re-exports for tests / endpoints that look for webhook_processor.
__all__ = [
    "InboundAcceptResult",
    "process_hub_inbound_event",
    "enqueue_if_needed",
    "accept_inbound_webhook",
]
