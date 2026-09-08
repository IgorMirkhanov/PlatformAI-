"""WhatsApp QR session management + test tools (Baileys bridge)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter, rate_limit_key_org
from app.core.rbac import get_current_user
from app.models.channels import HubChannelType
from app.models.core_models import Bot
from app.models.users import User
from app.services.channels_service import channels_hub_service
from app.services.whatsapp_qr_service import whatsapp_qr_service

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


class WhatsAppTestMessageRequest(BaseModel):
    to: str = Field(min_length=5, max_length=32, description="E.164-ish phone digits")
    text: str = Field(min_length=1, max_length=1000)


class WhatsAppSessionStatusResponse(BaseModel):
    bot_id: str
    status: str
    phone: str | None = None
    push_name: str | None = None
    connected_at: str | None = None
    has_qr: bool = False
    qr_base64: str | None = None
    hub_connected: bool = False
    hub_reference_id: str | None = None


async def _require_bot(db: AsyncSession, bot_id: uuid.UUID, user: User) -> Bot:
    bot = await db.get(Bot, bot_id)
    if bot is None or bot.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found.")
    if bool(getattr(user, "is_superadmin", False)):
        return bot
    if bot.user_id == user.id:
        return bot
    if bot.organization_id and bot.organization_id == user.company_id:
        return bot
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")


@router.get(
    "/{bot_id}/session",
    response_model=WhatsAppSessionStatusResponse,
    summary="WhatsApp QR session status (Baileys + hub)",
)
async def get_whatsapp_session(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatsAppSessionStatusResponse:
    await _require_bot(db, bot_id, current_user)
    live = await whatsapp_qr_service.get_session_status(bot_id)
    hub = await channels_hub_service.list_channels(db, bot_id)
    qr_hub = next(
        (c for c in hub.channels if c.channel_type == HubChannelType.WHATSAPP_QR),
        None,
    )
    qr_b64 = live.get("qr_base64")
    return WhatsAppSessionStatusResponse(
        bot_id=str(bot_id),
        status=str(live.get("status") or "disconnected"),
        phone=live.get("phone") or (qr_hub.reference_id if qr_hub else None),
        push_name=live.get("push_name"),
        connected_at=live.get("connected_at"),
        has_qr=bool(live.get("has_qr") or qr_b64),
        qr_base64=str(qr_b64) if qr_b64 else None,
        hub_connected=bool(qr_hub.connected) if qr_hub else False,
        hub_reference_id=qr_hub.reference_id if qr_hub else None,
    )


@router.post(
    "/{bot_id}/session/start",
    summary="Start / resume WhatsApp QR session",
)
async def start_whatsapp_session(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_bot(db, bot_id, current_user)
    return await whatsapp_qr_service.start_session(bot_id)


@router.post(
    "/{bot_id}/session/refresh-qr",
    summary="Force refresh WhatsApp QR (new pairing code)",
)
async def refresh_whatsapp_qr(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_bot(db, bot_id, current_user)
    return await whatsapp_qr_service.refresh_qr(bot_id)


@router.post(
    "/{bot_id}/session/stop",
    summary="Disconnect WhatsApp QR session and wipe auth files",
)
async def stop_whatsapp_session(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_bot(db, bot_id, current_user)
    await channels_hub_service.disconnect_channel(db, bot_id, HubChannelType.WHATSAPP_QR)
    await whatsapp_qr_service.stop_session(bot_id)
    await db.commit()
    return {"ok": True, "bot_id": str(bot_id), "status": "disconnected"}


@router.post(
    "/{bot_id}/test-message",
    summary="Send a connectivity test message via Baileys",
)
@limiter.limit("5/minute", key_func=rate_limit_key_org)
async def send_whatsapp_test_message(
    request: Request,
    bot_id: uuid.UUID,
    payload: WhatsAppTestMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_bot(db, bot_id, current_user)
    try:
        await whatsapp_qr_service.send_text_message(
            bot_id=bot_id,
            to=payload.to,
            text=payload.text,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc)[:300] or "Failed to send test message.",
        ) from exc
    return {"ok": True, "to": payload.to, "message": "Test message sent."}
