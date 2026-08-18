"""CRM real-time fan-out over the shared operator WebSocket gateway."""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from app.core.websocket import WSEventType
from app.core.ws_pubsub import publish_operator_ws_event
from app.schemas.crm.deals import CrmDealRead


def _safe_publish(
    *,
    organization_id: uuid.UUID,
    event: WSEventType,
    payload: dict[str, Any],
) -> None:
    """
    Publish to Redis ``chat_events`` for multi-worker fan-out.

    Never raises — WS/broker failures must not roll back CRM mutations.
    Tenant isolation: ``company_id`` = organization_id (same as operator WS room).
    """
    try:
        publish_operator_ws_event(
            company_id=str(organization_id),
            event=event.value,
            payload=payload,
        )
    except Exception as exc:
        logger.warning(
            "CRM.ws_publish_failed | org={org} event={event} error={error}",
            org=organization_id,
            event=event.value,
            error=str(exc),
        )


def publish_deal_created(
    organization_id: uuid.UUID,
    deal: CrmDealRead,
    *,
    actor_id: uuid.UUID | None = None,
) -> None:
    deal_payload = deal.model_dump(mode="json")
    _safe_publish(
        organization_id=organization_id,
        event=WSEventType.CRM_DEAL_CREATED,
        payload={
            "topic": "crm",
            "type": "deal.created",
            "organization_id": str(organization_id),
            "actor_id": str(actor_id) if actor_id else None,
            "deal": deal_payload,
        },
    )


def publish_deal_updated(
    organization_id: uuid.UUID,
    *,
    deal_id: uuid.UUID,
    stage_id: uuid.UUID,
    pipeline_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    _safe_publish(
        organization_id=organization_id,
        event=WSEventType.CRM_DEAL_UPDATED,
        payload={
            "topic": "crm",
            "type": "deal.updated",
            "organization_id": str(organization_id),
            "deal_id": str(deal_id),
            "stage_id": str(stage_id),
            "pipeline_id": str(pipeline_id) if pipeline_id else None,
            "actor_id": str(actor_id) if actor_id else None,
        },
    )


def publish_deal_closed(
    organization_id: uuid.UUID,
    *,
    deal_id: uuid.UUID,
    status: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    _safe_publish(
        organization_id=organization_id,
        event=WSEventType.CRM_DEAL_CLOSED,
        payload={
            "topic": "crm",
            "type": "deal.closed",
            "organization_id": str(organization_id),
            "deal_id": str(deal_id),
            "status": status,
            "actor_id": str(actor_id) if actor_id else None,
        },
    )
