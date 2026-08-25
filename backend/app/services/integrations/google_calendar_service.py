"""Google Calendar OAuth, token refresh, and LLM calendar tools."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from loguru import logger

from app.core.config import resolve_webhook_base_url, settings
from app.models.core_models import Bot
from sqlalchemy.ext.asyncio import AsyncSession

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


def _encode_oauth_state(bot_id: uuid.UUID) -> str:
    payload = {"bot_id": str(bot_id), "ts": datetime.now(timezone.utc).isoformat()}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def decode_oauth_state(state: str) -> uuid.UUID:
    padded = state + "=" * (-len(state) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    return uuid.UUID(str(data["bot_id"]))


def build_google_auth_url(bot_id: uuid.UUID) -> tuple[str, str]:
    client_id = (settings.GOOGLE_CLIENT_ID or "").strip()
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID is not configured.")
    redirect_uri = f"{resolve_webhook_base_url()}/api/v1/integrations/google/callback"
    state = _encode_oauth_state(bot_id)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}", state


async def exchange_google_code(code: str) -> dict[str, Any]:
    client_id = (settings.GOOGLE_CLIENT_ID or "").strip()
    client_secret = (settings.GOOGLE_CLIENT_SECRET or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Google OAuth client credentials are not configured.")
    redirect_uri = f"{resolve_webhook_base_url()}/api/v1/integrations/google/callback"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        return response.json()


async def get_valid_google_token(bot: Bot, config: dict[str, Any]) -> str:
    """Return a usable Google access token, refreshing when needed."""
    from app.services.bot_app_integrations_service import bot_app_integrations_service

    token = str(config.get("access_token") or "").strip()
    expires_at = config.get("expires_at")
    if token and isinstance(expires_at, str):
        try:
            if datetime.fromisoformat(expires_at.replace("Z", "+00:00")) > datetime.now(timezone.utc):
                return token
        except ValueError:
            pass
    elif token and not expires_at:
        return token

    return await bot_app_integrations_service._ensure_google_access_token(bot, config)


async def check_calendar_availability(
    bot: Bot,
    *,
    start_iso: str,
    end_iso: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    access_token = await get_valid_google_token(bot, config)
    calendar_id = str(config.get("calendar_id") or "primary")
    params = {
        "timeMin": start_iso,
        "timeMax": end_iso,
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        response.raise_for_status()
        events = response.json().get("items") or []
    return {
        "available": len(events) == 0,
        "busy_slots": len(events),
        "events": [
            {"summary": item.get("summary"), "start": item.get("start"), "end": item.get("end")}
            for item in events[:10]
        ],
    }


async def create_calendar_event(
    bot: Bot,
    *,
    title: str,
    start_iso: str,
    end_iso: str,
    client_email: str | None = None,
    client_phone: str | None = None,
    config: dict[str, Any],
) -> dict[str, Any]:
    access_token = await get_valid_google_token(bot, config)
    calendar_id = str(config.get("calendar_id") or "primary")
    description_parts = [p for p in (client_phone, client_email) if p]
    body: dict[str, Any] = {
        "summary": title,
        "description": " · ".join(description_parts),
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if client_email:
        body["attendees"] = [{"email": client_email}]
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
        )
        response.raise_for_status()
        data = response.json()
    logger.info(
        "GoogleCalendar.event_created | bot_id={bot_id} event_id={event_id}",
        bot_id=bot.id,
        event_id=data.get("id"),
    )
    return {"event_id": data.get("id"), "html_link": data.get("htmlLink"), "status": "created"}


async def persist_google_tokens(
    db: AsyncSession,
    bot_id: uuid.UUID,
    token_payload: dict[str, Any],
) -> dict[str, Any]:
    from app.services.bot_app_integrations_service import bot_app_integrations_service

    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    access_token = str(token_payload.get("access_token") or "").strip()
    expires_in = int(token_payload.get("expires_in") or 3600)
    expires_at = datetime.now(timezone.utc).timestamp() + expires_in
    expires_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

    return await bot_app_integrations_service.connect(
        db,
        bot_id,
        "google_calendar",
        {
            "refresh_token": refresh_token,
            "access_token": access_token,
            "expires_at": expires_iso,
            "calendar_id": "primary",
            "client_id": settings.GOOGLE_CLIENT_ID or "",
            "client_secret": settings.GOOGLE_CLIENT_SECRET or "",
        },
    )
