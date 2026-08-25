"""Celery + Redis Integration Hub queue (BullMQ analog).

HTTP path: verify signature → persist webhook_events (received) → 200 → job.
Consumer: claim/dedup by external_event_id → normalize → resolve workspace/agent
from connection_id → AI runtime (messaging) or CRM side-effects.
Outbound adapter calls: one in-flight lock per connection_id + provider rate limits.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.models.integration_hub import (
    AgentActionStatus,
    HubConnectionStatus,
    IntegrationAgentAction,
    IntegrationConnection,
    IntegrationWebhookEvent,
    WebhookEventStatus,
)

_OUTBOUND_LOCK_PREFIX = "ihub:lock:outbound:"
# Legacy prefix kept for cleanup during rolling deploys.
_OUTBOUND_LOCK_PREFIX_LEGACY = "ihub:out:lock:"

# Ceiling for webhook consumer retries before dead_letter (checklist §2 / QA §4).
MAX_RETRIES = max(0, int(getattr(settings, "HUB_WEBHOOK_MAX_RETRIES", 8) or 8))


def outbound_lock_ttl() -> int:
    """TTL must expire if the worker dies mid-job (OOM / deploy / kill -9)."""
    return max(15, int(getattr(settings, "HUB_OUTBOUND_LOCK_TTL_SECONDS", 90) or 90))


def outbound_job_timeout_seconds() -> float:
    """Soft job timeout — always strictly below the Redis lock TTL."""
    ttl = outbound_lock_ttl()
    configured = int(getattr(settings, "HUB_OUTBOUND_JOB_TIMEOUT_SECONDS", 60) or 60)
    # Keep at least 5s headroom under the lock so EX always wins on kill -9.
    return float(max(5, min(configured, ttl - 5)))


def outbound_lock_key(connection_id: str) -> str:
    return f"{_OUTBOUND_LOCK_PREFIX}{connection_id}"


def webhook_retry_countdown(retry_count: int) -> int:
    """Exponential backoff seconds for the next webhook attempt."""
    attempt = max(0, int(retry_count) - 1)
    return min(120, 2 ** attempt)

_REDACT_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "application_token",
        "client_secret",
        "client_access_token",
        "api_key",
        "authorization",
        "password",
        "secret",
        "token",
    }
)

CRM_ADAPTER_ACTIONS = frozenset(
    {
        "create_contact",
        "update_contact",
        "find_contact",
        "create_deal",
        "update_deal_stage",
        "add_note",
    }
)
MESSAGING_ADAPTER_ACTIONS = frozenset({"send_message"})
PAYMENT_ADAPTER_ACTIONS = frozenset({"create_invoice"})
ACTION_ALIASES = {
    "createContact": "create_contact",
    "updateContact": "update_contact",
    "findContact": "find_contact",
    "createDeal": "create_deal",
    "updateDealStage": "update_deal_stage",
    "addNote": "add_note",
    "sendMessage": "send_message",
    "createInvoice": "create_invoice",
}


def canonical_action_type(action_type: str) -> str:
    raw = (action_type or "").strip()
    return ACTION_ALIASES.get(raw, raw)


class OutboundConnectionBusy(Exception):
    """Another outbound job is already running for this connection_id."""


class ConnectionRevokedError(Exception):
    """Outbound actions blocked for revoked/expired (or missing) connections."""

    def __init__(self, connection_id: str, status: str | None = None) -> None:
        self.connection_id = connection_id
        self.status = status or "missing"
        super().__init__(
            f"Integration connection {connection_id} is {self.status}; "
            "outbound actions are not allowed."
        )


OUTBOUND_BLOCKED_STATUSES = frozenset(
    {
        HubConnectionStatus.REVOKED.value,
        HubConnectionStatus.EXPIRED.value,
    }
)


async def assert_connection_allows_outbound(
    db: AsyncSession,
    connection_id: uuid.UUID | str,
) -> IntegrationConnection:
    """Raise ``ConnectionRevokedError`` before any provider HTTP call."""
    cid = uuid.UUID(str(connection_id))
    row = await db.get(IntegrationConnection, cid)
    if row is None:
        raise ConnectionRevokedError(str(cid), "missing")
    status = (row.status or "").strip().lower()
    if status in OUTBOUND_BLOCKED_STATUSES:
        raise ConnectionRevokedError(str(cid), status)
    return row


def assert_connection_allows_outbound_sync(connection_id: uuid.UUID | str) -> None:
    """Sync guard for ``enqueue_adapter_action`` (no external API)."""
    from app.core.database import async_session_factory, run_celery_async

    async def _check() -> None:
        async with async_session_factory() as db:
            await assert_connection_allows_outbound(db, connection_id)

    run_celery_async(_check())


def sanitize_payload(value: Any, *, depth: int = 0) -> Any:
    """Strip secrets before persisting webhook/agent payloads."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _REDACT_KEYS:
                out[str(key)] = "[redacted]"
            else:
                out[str(key)] = sanitize_payload(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [sanitize_payload(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def serialize_action_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if is_dataclass(result) and not isinstance(result, type):
        return sanitize_payload(asdict(result))
    if isinstance(result, dict):
        return sanitize_payload(result)
    if hasattr(result, "id"):
        payload = {"id": str(getattr(result, "id"))}
        for field in (
            "name",
            "phone",
            "email",
            "title",
            "stage_id",
            "contact_id",
            "amount",
            "description",
            "payment_url",
            "callback_url",
            "status",
            "order_id",
        ):
            if getattr(result, field, None) is not None:
                payload[field] = getattr(result, field)
        return sanitize_payload(payload)
    return {"result": str(result)}


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def record_received_event(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    provider: str,
    external_event_id: str,
    payload: dict[str, Any],
) -> uuid.UUID | None:
    """Insert webhook_events with status=received.

    Returns the new row id, or ``None`` when the delivery is a duplicate so
    callers must not re-enqueue Celery work. Prefer ``process_hub_inbound_event``.
    """
    from app.services.integration_hub.webhook_dedup import accept_inbound_webhook

    result = await accept_inbound_webhook(
        db,
        connection=connection,
        provider=provider,
        external_event_id=external_event_id,
        payload=payload,
    )
    if result.should_enqueue:
        return result.event_id
    return None


def enqueue_hub_webhook_job(event_id: uuid.UUID) -> None:
    from app.tasks.hub_queue_tasks import process_hub_webhook_event_task

    process_hub_webhook_event_task.apply_async(
        args=[str(event_id)],
        queue=settings.CELERY_HUB_INBOUND_QUEUE,
    )


async def record_received_and_enqueue(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    provider: str,
    external_event_id: str,
    payload: dict[str, Any],
    commit: bool = False,
) -> uuid.UUID | None:
    """Persist received, optionally commit, enqueue consumer job. Caller still returns 200."""
    event_id = await record_received_event(
        db,
        connection=connection,
        provider=provider,
        external_event_id=external_event_id,
        payload=payload,
    )
    if commit:
        await db.commit()
        if event_id is not None:
            enqueue_hub_webhook_job(event_id)
    return event_id


def enqueue_adapter_action(
    connection_id: uuid.UUID | str,
    action_type: str,
    params: dict[str, Any] | None = None,
    *,
    wait: bool = False,
    timeout: float = 45.0,
) -> Any:
    """Queue an outbound adapter call grouped by connection_id.

    Rejects ``revoked`` / ``expired`` immediately (``ConnectionRevokedError``)
    so Celery never hits the provider. ``wait=True`` blocks for the worker result.
    """
    from app.tasks.hub_queue_tasks import execute_hub_adapter_action_task

    assert_connection_allows_outbound_sync(connection_id)

    result = execute_hub_adapter_action_task.apply_async(
        args=[str(connection_id), str(action_type), dict(params or {})],
        queue=settings.CELERY_HUB_OUTBOUND_QUEUE,
    )
    if wait:
        return result.get(timeout=timeout)
    return {"queued": True, "task_id": result.id}


def try_acquire_outbound_lock(connection_id: str, *, ttl: int | None = None) -> bool:
    """Serialize outbound jobs per connection_id with Redis SET NX EX.

    Key: ``ihub:lock:outbound:{connection_id}``.
    Fail-open if Redis is down. TTL guarantees unlock after worker death.
    """
    key = outbound_lock_key(connection_id)
    lock_ttl = outbound_lock_ttl() if ttl is None else max(15, int(ttl))
    # Job soft-timeout is always below lock TTL — assert invariant for ops.
    if outbound_job_timeout_seconds() >= lock_ttl:
        logger.warning(
            "IntegrationHub.outbound_lock_ttl_too_low | ttl={ttl} job_timeout={job}",
            ttl=lock_ttl,
            job=outbound_job_timeout_seconds(),
        )
    try:
        client = get_redis_client()
        return bool(client.set(key, "1", nx=True, ex=lock_ttl))
    except Exception as exc:
        logger.warning(
            "IntegrationHub.outbound_lock_unavailable | connection_id={id} error={error}",
            id=connection_id,
            error=str(exc),
        )
        return True


def release_outbound_lock(connection_id: str) -> None:
    try:
        client = get_redis_client()
        client.delete(outbound_lock_key(connection_id))
        client.delete(f"{_OUTBOUND_LOCK_PREFIX_LEGACY}{connection_id}")
    except Exception as exc:
        logger.warning(
            "IntegrationHub.outbound_lock_release_failed | connection_id={id} error={error}",
            id=connection_id,
            error=str(exc),
        )


def _stale_processing_cutoff() -> datetime:
    from datetime import timedelta

    seconds = max(60, int(getattr(settings, "HUB_WEBHOOK_STALE_PROCESSING_SECONDS", 300) or 300))
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def claim_webhook_event(
    db: AsyncSession,
    event_id: uuid.UUID,
) -> tuple[str, IntegrationWebhookEvent | None]:
    """FOR UPDATE claim. Returns (claimed|duplicate|dead_letter|missing, event)."""
    event = await db.scalar(
        select(IntegrationWebhookEvent)
        .where(IntegrationWebhookEvent.id == event_id)
        .with_for_update()
    )
    if event is None:
        return "missing", None
    if event.status == WebhookEventStatus.DEAD_LETTER.value:
        return "dead_letter", event
    if event.status == WebhookEventStatus.PROCESSED.value:
        return "duplicate", event
    if event.status == WebhookEventStatus.DUPLICATE.value:
        return "duplicate", event
    # Stale PROCESSING (worker crash) or ERROR from a previous attempt → reclaim.
    if event.status == WebhookEventStatus.PROCESSING.value:
        if event.created_at is not None:
            created = event.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created > _stale_processing_cutoff():
                return "duplicate", event
    elif event.status not in {
        WebhookEventStatus.RECEIVED.value,
        WebhookEventStatus.ERROR.value,
    }:
        return "duplicate", event
    sibling = await db.scalar(
        select(IntegrationWebhookEvent.id).where(
            IntegrationWebhookEvent.provider == event.provider,
            IntegrationWebhookEvent.external_event_id == event.external_event_id,
            IntegrationWebhookEvent.status.in_(
                (
                    WebhookEventStatus.PROCESSING.value,
                    WebhookEventStatus.PROCESSED.value,
                )
            ),
            IntegrationWebhookEvent.id != event.id,
        )
    )
    if sibling is not None:
        event.status = WebhookEventStatus.DUPLICATE.value
        event.processed_at = datetime.now(timezone.utc)
        return "duplicate", event
    event.status = WebhookEventStatus.PROCESSING.value
    event.error = None
    return "claimed", event


async def mark_webhook_event(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    status: str,
    error: str | None = None,
) -> None:
    event = await db.get(IntegrationWebhookEvent, event_id)
    if event is None:
        return
    event.status = status
    event.error = (error or "")[:2000] or None
    if status in {
        WebhookEventStatus.PROCESSED.value,
        WebhookEventStatus.DUPLICATE.value,
        WebhookEventStatus.ERROR.value,
        WebhookEventStatus.DEAD_LETTER.value,
    }:
        event.processed_at = datetime.now(timezone.utc)


async def reset_webhook_event_for_retry(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    error: str | None = None,
    countdown: int | None = None,
) -> IntegrationWebhookEvent | None:
    """Return event to received, bump retry_count, set next_retry_at (backoff)."""
    from datetime import timedelta

    event = await db.get(IntegrationWebhookEvent, event_id)
    if event is None:
        return None
    if event.status in {
        WebhookEventStatus.PROCESSED.value,
        WebhookEventStatus.DUPLICATE.value,
        WebhookEventStatus.DEAD_LETTER.value,
    }:
        return event
    event.retry_count = int(getattr(event, "retry_count", 0) or 0) + 1
    delay = (
        max(0, int(countdown))
        if countdown is not None
        else webhook_retry_countdown(event.retry_count)
    )
    event.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    event.status = WebhookEventStatus.RECEIVED.value
    event.error = (error or "")[:2000] or None
    event.processed_at = None
    return event


def normalize_hub_event(
    *,
    event: IntegrationWebhookEvent,
    connection: IntegrationConnection,
) -> dict[str, Any]:
    payload = event.payload_json if isinstance(event.payload_json, dict) else {}
    event_type = str(payload.get("type") or payload.get("event") or f"{event.provider}.event")
    return {
        "type": event_type,
        "provider": event.provider,
        "external_event_id": event.external_event_id,
        "workspace_id": str(connection.organization_id),
        "agent_id": str(connection.bot_id) if connection.bot_id else None,
        "connection_id": str(connection.id),
        "payload": payload,
    }


async def persist_agent_action(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    action_type: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None,
    status: str,
    error: str | None = None,
    duration_ms: int | None = None,
    external_id: str | None = None,
) -> IntegrationAgentAction:
    row = IntegrationAgentAction(
        connection_id=connection.id,
        organization_id=connection.organization_id,
        bot_id=connection.bot_id,
        action_type=action_type[:64],
        external_id=(external_id or "")[:255] or None,
        status=status[:24] or AgentActionStatus.OK.value,
        error=(error or "")[:2000] or None,
        duration_ms=duration_ms,
        request_json=sanitize_payload(request_payload) if isinstance(request_payload, dict) else {},
        response_json=sanitize_payload(response_payload) if isinstance(response_payload, dict) else {},
    )
    db.add(row)
    await db.flush()
    return row
