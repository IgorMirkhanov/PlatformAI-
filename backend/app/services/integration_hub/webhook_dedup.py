"""Inbound webhook accept: Redis+DB dedup and workspace mismatch → dead_letter."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import get_redis_client
from app.models.integration_hub import (
    IntegrationConnection,
    IntegrationWebhookEvent,
    WebhookEventStatus,
)
from app.services.integration_hub.queue import (
    _payload_hash,
    enqueue_hub_webhook_job,
    sanitize_payload,
)

_DEDUP_PREFIX = "webhook_dedup:"
_DEDUP_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class InboundAcceptResult:
    """Outcome of accepting a provider webhook delivery."""

    event_id: uuid.UUID | None
    is_new: bool
    duplicate: bool
    dead_letter: bool
    should_enqueue: bool


def redis_dedup_key(provider: str, external_event_id: str) -> str:
    return f"{_DEDUP_PREFIX}{(provider or '').strip().lower()}:{str(external_event_id)[:255]}"


def claim_webhook_dedup_key(provider: str, external_event_id: str) -> bool:
    """SET NX EX on webhook_dedup:{provider}:{external_event_id}. True = first sighting."""
    key = redis_dedup_key(provider, external_event_id)
    try:
        client = get_redis_client()
        return bool(client.set(key, "1", nx=True, ex=_DEDUP_TTL_SECONDS))
    except Exception as exc:
        logger.warning(
            "WebhookDedup.redis_unavailable | provider={provider} error={error}",
            provider=provider,
            error=type(exc).__name__,
        )
        # Fail-open to DB unique constraint so we still dedup under Redis outage.
        return True


def extract_payload_workspace_id(payload: dict[str, Any] | None) -> uuid.UUID | None:
    if not isinstance(payload, dict):
        return None
    for key in ("workspace_id", "organization_id", "org_id", "company_id"):
        raw = payload.get(key)
        if raw in (None, ""):
            continue
        try:
            return uuid.UUID(str(raw))
        except (TypeError, ValueError):
            continue
    nested = payload.get("auth") if isinstance(payload.get("auth"), dict) else None
    if nested:
        return extract_payload_workspace_id(nested)
    return None


async def accept_inbound_webhook(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    provider: str,
    external_event_id: str,
    payload: dict[str, Any],
) -> InboundAcceptResult:
    """Persist a webhook once; duplicates skip business enqueue; mismatch → dead_letter."""
    provider_key = (provider or connection.provider or "").strip().lower()
    ext_id = str(external_event_id)[:255]
    safe_payload = sanitize_payload(payload if isinstance(payload, dict) else {})
    if not isinstance(safe_payload, dict):
        safe_payload = {}

    if not claim_webhook_dedup_key(provider_key, ext_id):
        logger.info(
            "WebhookDedup.hit | provider={provider} external_event_id={ext}",
            provider=provider_key,
            ext=ext_id,
        )
        return InboundAcceptResult(
            event_id=None,
            is_new=False,
            duplicate=True,
            dead_letter=False,
            should_enqueue=False,
        )

    hinted = extract_payload_workspace_id(safe_payload)
    mismatch = hinted is not None and hinted != connection.organization_id
    initial_status = (
        WebhookEventStatus.DEAD_LETTER.value
        if mismatch
        else WebhookEventStatus.RECEIVED.value
    )
    error = "workspace_mismatch" if mismatch else None

    event_uuid = uuid.uuid4()
    stmt = (
        pg_insert(IntegrationWebhookEvent)
        .values(
            id=event_uuid,
            connection_id=connection.id,
            organization_id=connection.organization_id,
            provider=provider_key,
            external_event_id=ext_id,
            payload_hash=_payload_hash(safe_payload),
            payload_json=safe_payload,
            status=initial_status,
            error=error,
        )
        .on_conflict_do_nothing(constraint="uq_integration_webhook_events_provider_ext")
        .returning(IntegrationWebhookEvent.id)
    )
    inserted = await db.scalar(stmt)
    if inserted is None:
        return InboundAcceptResult(
            event_id=await db.scalar(
                select(IntegrationWebhookEvent.id).where(
                    IntegrationWebhookEvent.provider == provider_key,
                    IntegrationWebhookEvent.external_event_id == ext_id,
                )
            ),
            is_new=False,
            duplicate=True,
            dead_letter=False,
            should_enqueue=False,
        )

    if mismatch:
        logger.warning(
            "WebhookDedup.workspace_mismatch | connection_id={cid} "
            "connection_org={org} payload_org={hint}",
            cid=connection.id,
            org=connection.organization_id,
            hint=hinted,
        )
        return InboundAcceptResult(
            event_id=inserted,
            is_new=True,
            duplicate=False,
            dead_letter=True,
            should_enqueue=False,
        )

    return InboundAcceptResult(
        event_id=inserted,
        is_new=True,
        duplicate=False,
        dead_letter=False,
        should_enqueue=True,
    )


def enqueue_if_needed(result: InboundAcceptResult) -> None:
    if result.should_enqueue and result.event_id is not None:
        enqueue_hub_webhook_job(result.event_id)
