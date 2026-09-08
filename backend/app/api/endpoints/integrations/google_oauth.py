"""Integrations HTTP endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.config import settings
from app.core.database import get_db
from app.core.rbac import Permission
from app.models.core_models import Bot
from app.services.integrations.google_calendar_service import (
    build_google_auth_url,
    decode_oauth_purpose,
    decode_oauth_state,
    exchange_google_code,
    persist_google_tokens,
)

router = APIRouter(tags=["integrations-google"])


@router.get("/bots/{bot_id}/integrations/google/auth-url", summary="Start Google OAuth2 flow")
async def google_calendar_auth_url(
    bot_id: uuid.UUID,
    purpose: str = Query(default="google"),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_INTEGRATIONS)),
) -> dict[str, str]:
    try:
        auth_url, state = build_google_auth_url(bot_id, purpose=purpose)
        return {"auth_url": auth_url, "state": state}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/integrations/google/callback", summary="Google OAuth2 callback")
async def google_calendar_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    if error:
        frontend = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
        return RedirectResponse(
            url=f"{frontend}/dashboard/integrations?google=error&message={error}",
            status_code=status.HTTP_302_FOUND,
        )
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth code/state.")

    try:
        bot_id = decode_oauth_state(state)
        purpose = decode_oauth_purpose(state)
        token_payload = await exchange_google_code(code)
        await persist_google_tokens(db, bot_id, token_payload, purpose=purpose)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        frontend = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
        return RedirectResponse(
            url=f"{frontend}/dashboard/integrations?google=error&message={str(exc)[:120]}",
            status_code=status.HTTP_302_FOUND,
        )

    frontend = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
    return RedirectResponse(
        url=f"{frontend}/dashboard/integrations?botId={bot_id}&google=connected",
        status_code=status.HTTP_302_FOUND,
    )
