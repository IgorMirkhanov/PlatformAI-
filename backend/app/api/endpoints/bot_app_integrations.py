"""Bot Integrations catalog API — AmoCRM, Bitrix24, Google Calendar, Kaspi, Jivo, U-ON."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission
from app.models.core_models import Bot
from app.services.bot_app_integrations_service import (
    INTEGRATION_PLATFORMS,
    bot_app_integrations_service,
)

router = APIRouter(prefix="/bots", tags=["bot-integrations"])


class IntegrationConnectRequest(BaseModel):
    # Shared / multi-platform fields (ignored when unused).
    base_domain: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    authorization_code: str | None = None
    redirect_uri: str | None = None
    webhook_url: str | None = None
    refresh_token: str | None = None
    access_token: str | None = None
    calendar_id: str | None = None
    merchant_id: str | None = None
    merchant_token: str | None = None
    api_key: str | None = None
    secret_key: str | None = None
    token: str | None = None
    provider_id: str | None = None
    base_url: str | None = None
    mode: str | None = None
    min_amount_kzt: float | None = None
    payment_base_url: str | None = None
    sync_enabled: bool | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class IntegrationActionRequest(BaseModel):
    """Runtime actions triggered from flow / inbox / test UI."""

    action: str
    summary: str | None = None
    start_iso: str | None = None
    end_iso: str | None = None
    description: str | None = None
    attendee_email: str | None = None
    amount_kzt: float | None = None
    order_id: str | None = None
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    note: str | None = None
    destination: str | None = None
    budget: str | None = None
    client_id: str | None = None
    text: str | None = None


@router.get(
    "/{bot_id}/app-integrations/status",
    summary="Status of all Integrations-tab platforms",
)
async def get_app_integrations_status(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> dict[str, Any]:
    try:
        return await bot_app_integrations_service.get_status(db, bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{bot_id}/app-integrations/{platform}/connect",
    summary="Connect an Integrations-tab platform",
)
async def connect_app_integration(
    bot_id: uuid.UUID,
    platform: str,
    payload: IntegrationConnectRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> dict[str, Any]:
    if platform not in INTEGRATION_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"platform must be one of: {', '.join(INTEGRATION_PLATFORMS)}",
        )
    try:
        result = await bot_app_integrations_service.connect(
            db, bot_id, platform, payload.model_dump(exclude_none=True)
        )
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception(
            "AppIntegrations.connect_failed | bot_id={bot_id} platform={platform} error={error}",
            bot_id=bot_id,
            platform=platform,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect integration.",
        ) from exc


@router.delete(
    "/{bot_id}/app-integrations/{platform}",
    summary="Disconnect an Integrations-tab platform",
)
async def disconnect_app_integration(
    bot_id: uuid.UUID,
    platform: str,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> dict[str, Any]:
    try:
        result = await bot_app_integrations_service.disconnect(db, bot_id, platform)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch(
    "/{bot_id}/app-integrations/{platform}",
    summary="Patch sync/mapping for an integration",
)
async def patch_app_integration(
    bot_id: uuid.UUID,
    platform: str,
    payload: IntegrationConnectRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> dict[str, Any]:
    try:
        result = await bot_app_integrations_service.patch(
            db, bot_id, platform, payload.model_dump(exclude_none=True)
        )
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{bot_id}/app-integrations/{platform}/actions",
    summary="Run a runtime integration action (calendar event, invoice, lead, …)",
)
async def run_app_integration_action(
    bot_id: uuid.UUID,
    platform: str,
    payload: IntegrationActionRequest,
    db: AsyncSession = Depends(get_db),
    bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> dict[str, Any]:
    _ = bot_id
    action = (payload.action or "").strip().lower()
    try:
        if platform == "google_calendar" and action == "create_event":
            if not payload.summary or not payload.start_iso or not payload.end_iso:
                raise ValueError("summary, start_iso and end_iso are required.")
            data = await bot_app_integrations_service.create_calendar_event(
                bot,
                summary=payload.summary,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
                description=payload.description or "",
                attendee_email=payload.attendee_email,
            )
            return {"ok": True, "result": data}

        if platform == "google_calendar" and action == "check_availability":
            if not payload.start_iso or not payload.end_iso:
                raise ValueError("start_iso and end_iso are required.")
            data = await bot_app_integrations_service.check_calendar_availability(
                bot,
                start_iso=payload.start_iso,
                end_iso=payload.end_iso,
            )
            return {"ok": True, "result": data}

        if platform == "kaspi_pay" and action == "create_invoice":
            if payload.amount_kzt is None:
                raise ValueError("amount_kzt is required.")
            order_id = payload.order_id or f"ord-{uuid.uuid4().hex[:12]}"
            data = await bot_app_integrations_service.create_kaspi_invoice(
                bot,
                amount_kzt=float(payload.amount_kzt),
                order_id=order_id,
                description=payload.description or "",
            )
            return {"ok": True, "result": data}

        if platform == "kaspi_receipts" and action == "verify_text":
            data = await bot_app_integrations_service.verify_kaspi_receipt_text(
                payload.text or ""
            )
            return {"ok": True, "result": data}

        if platform == "uon" and action == "create_lead":
            if not payload.name:
                raise ValueError("name is required.")
            data = await bot_app_integrations_service.create_uon_lead(
                bot,
                name=payload.name,
                phone=payload.phone or "",
                email=payload.email or "",
                note=payload.note or "",
                destination=payload.destination or "",
                budget=payload.budget or "",
            )
            return {"ok": True, "result": data}

        if platform == "jivo" and action == "send_message":
            if not payload.client_id or not payload.text:
                raise ValueError("client_id and text are required.")
            data = await bot_app_integrations_service.send_jivo_message(
                bot, client_id=payload.client_id, text=payload.text
            )
            return {"ok": True, "result": data}

        raise ValueError(f"Unsupported action '{action}' for platform '{platform}'.")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "AppIntegrations.action_failed | bot_id={bot_id} platform={platform} action={action}",
            bot_id=bot_id,
            platform=platform,
            action=action,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Integration action failed.",
        ) from exc


@router.post(
    "/{bot_id}/app-integrations/kaspi_receipts/verify-upload",
    summary="Verify an uploaded Kaspi receipt PDF/image for this bot",
)
async def verify_kaspi_receipt_upload(
    bot_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> dict[str, Any]:
    _ = bot_id
    raw = await file.read()
    result = await bot_app_integrations_service.verify_kaspi_receipt_file(
        raw, file.filename or "receipt.bin"
    )
    return {"ok": True, "result": result}

