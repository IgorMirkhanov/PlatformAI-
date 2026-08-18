"""WhatsApp Cloud API Omnichannel webhook endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, rate_limit_key_org
from app.services.omnichannel.base_connector import ChannelConnectorError
from app.services.omnichannel.connectors.whatsapp_connector import WhatsAppConnector
from app.services.omnichannel.message_log_service import message_log_service

router = APIRouter(prefix="/omnichannel/whatsapp", tags=["omnichannel-whatsapp"])


class WhatsAppWebhookResult(BaseModel):
    status: str = "ok"
    logged: int = 0
    statuses_ignored: int = 0
    message_ids: list[str] = Field(default_factory=list)


def _build_connector(
    *,
    organization_id: uuid.UUID | None = None,
) -> WhatsAppConnector:
    return WhatsAppConnector(organization_id=organization_id)


@router.get(
    "/webhook",
    summary="Meta WhatsApp webhook verification",
    response_class=PlainTextResponse,
)
async def whatsapp_verify_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> PlainTextResponse:
    challenge = WhatsAppConnector.verify_webhook_static(
        hub_mode=hub_mode,
        hub_verify_token=hub_verify_token,
        hub_challenge=hub_challenge,
        expected_token=settings.WHATSAPP_VERIFY_TOKEN,
    )
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WhatsApp webhook verification failed.",
        )
    return PlainTextResponse(content=challenge, status_code=status.HTTP_200_OK)


@router.post(
    "/webhook",
    response_model=WhatsAppWebhookResult,
    summary="Receive WhatsApp Cloud API webhooks",
)
@limiter.limit("60/minute", key_func=rate_limit_key_org)
async def whatsapp_receive_webhook(
    request: Request,
    organization_id: uuid.UUID = Query(
        ...,
        description="Tenant that owns this WhatsApp channel binding.",
    ),
    db: AsyncSession = Depends(get_db),
) -> WhatsAppWebhookResult:
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON webhook body.",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body must be a JSON object.",
        )

    connector = _build_connector(organization_id=organization_id)
    statuses_ignored = _count_status_updates(payload)

    try:
        inbound_messages = connector.parse_all_inbound(payload)
    except ChannelConnectorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    logged_ids: list[str] = []
    for inbound in inbound_messages:
        try:
            await message_log_service.log_inbound(db, inbound)
            logged_ids.append(inbound.channel_message_id)
            await _fire_inbound_hooks(db, inbound)
        except Exception as exc:
            logger.exception(
                "Omnichannel.WhatsApp.log_failed | org={org} mid={mid} error={error}",
                org=organization_id,
                mid=inbound.channel_message_id,
                error=str(exc),
            )

    logger.info(
        "Omnichannel.WhatsApp.webhook | org={org} logged={n} statuses={s}",
        org=organization_id,
        n=len(logged_ids),
        s=statuses_ignored,
    )
    return WhatsAppWebhookResult(
        status="ok",
        logged=len(logged_ids),
        statuses_ignored=statuses_ignored,
        message_ids=logged_ids,
    )


def _count_status_updates(payload: dict[str, Any]) -> int:
    count = 0
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            statuses = value.get("statuses") or []
            if isinstance(statuses, list):
                count += len(statuses)
    return count


async def _fire_inbound_hooks(db: AsyncSession, inbound: Any) -> None:
    """Best-effort automation / CRM triggers (no-op when not wired)."""
    try:
        from app.services.crm.crm_usage_events import record_crm_usage_event  # noqa: F401
    except Exception:
        return
    # Future: enqueue flow / automation by InboundMessage.
    logger.debug(
        "Omnichannel.WhatsApp.hooks_skipped | mid={mid} (automation wiring deferred)",
        mid=getattr(inbound, "channel_message_id", None),
    )
