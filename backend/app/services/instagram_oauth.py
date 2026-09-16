"""Instagram Business Login (OAuth) — redirects the user to instagram.com."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from loguru import logger

from app.core.config import resolve_webhook_base_url, settings
from app.core.security import _jwt_secret
from app.services.integration_hub.oauth import frontend_result_url

_STATE_TYP = "ig_oauth"
_STATE_TTL = timedelta(minutes=15)
_SCOPES = "instagram_business_basic,instagram_business_manage_messages"
_GRAPH_VERSION = "v21.0"


class InstagramOAuthError(ValueError):
    """User-facing Instagram OAuth failure."""


def instagram_app_id() -> str:
    return (
        (getattr(settings, "INSTAGRAM_APP_ID", None) or "")
        or (getattr(settings, "META_APP_ID", None) or "")
        or ""
    ).strip()


def instagram_app_secret() -> str:
    return (
        (getattr(settings, "INSTAGRAM_APP_SECRET", None) or "")
        or (getattr(settings, "META_APP_SECRET", None) or "")
        or ""
    ).strip()


def instagram_oauth_callback_url() -> str:
    override = (getattr(settings, "INSTAGRAM_OAUTH_REDIRECT_URI", None) or "").strip()
    if override:
        return override.rstrip("/")
    return f"{resolve_webhook_base_url()}/api/v1/channels/instagram/oauth/callback"


def _require_app() -> tuple[str, str]:
    app_id = instagram_app_id()
    secret = instagram_app_secret()
    if not app_id or not secret:
        raise InstagramOAuthError(
            "Instagram OAuth не настроен: задайте INSTAGRAM_APP_ID и INSTAGRAM_APP_SECRET "
            "(или META_APP_ID / META_APP_SECRET) в .env.production. "
            "В Meta App Dashboard добавьте продукт Instagram и Redirect URI: "
            f"{instagram_oauth_callback_url()}"
        )
    return app_id, secret


def sign_instagram_oauth_state(*, bot_id: uuid.UUID, user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "typ": _STATE_TYP,
        "bot_id": str(bot_id),
        "user_id": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + _STATE_TTL).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_instagram_oauth_state(state: str) -> dict[str, Any]:
    if not (state or "").strip():
        raise InstagramOAuthError("Отсутствует OAuth state.")
    try:
        payload = jwt.decode(
            state.strip(),
            _jwt_secret(),
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise InstagramOAuthError("OAuth state недействителен или истёк.") from exc
    if payload.get("typ") != _STATE_TYP:
        raise InstagramOAuthError("Неверный тип OAuth state.")
    return payload


def build_instagram_authorize_url(*, bot_id: uuid.UUID, user_id: uuid.UUID) -> str:
    app_id, _secret = _require_app()
    params = {
        "client_id": app_id,
        "redirect_uri": instagram_oauth_callback_url(),
        "response_type": "code",
        "scope": _SCOPES,
        "state": sign_instagram_oauth_state(bot_id=bot_id, user_id=user_id),
    }
    return f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"


def instagram_frontend_result(*, status: str, message: str = "", bot_id: str = "") -> str:
    return frontend_result_url(
        provider="instagram",
        status=status,
        message=message[:180],
        bot_id=bot_id,
    )


async def exchange_instagram_code(code: str) -> dict[str, str]:
    app_id, secret = _require_app()
    redirect_uri = instagram_oauth_callback_url()
    async with httpx.AsyncClient(timeout=25.0) as http:
        short = await http.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": app_id,
                "client_secret": secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code.strip(),
            },
        )
        if short.status_code >= 400:
            logger.warning(
                "InstagramOAuth.token_exchange_failed | status={status} body={body}",
                status=short.status_code,
                body=short.text[:400],
            )
            raise InstagramOAuthError(
                "Instagram не выдал токен. Проверьте App ID/Secret и Redirect URI в кабинете Meta."
            )
        body = short.json() if short.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        token = str(body.get("access_token") or "").strip()
        user_id = str(body.get("user_id") or "").strip()
        if not token:
            raise InstagramOAuthError("Instagram вернул пустой access_token.")

        long_lived = token
        try:
            exchanged = await http.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": secret,
                    "access_token": token,
                },
            )
            if exchanged.status_code < 400:
                long_body = exchanged.json() if isinstance(exchanged.json(), dict) else {}
                long_lived = str(long_body.get("access_token") or token)
        except Exception as exc:
            logger.warning("InstagramOAuth.long_lived_failed | error={error}", error=str(exc))

        username = ""
        ig_id = user_id
        try:
            me = await http.get(
                f"https://graph.instagram.com/{_GRAPH_VERSION}/me",
                params={"fields": "user_id,username,name,id", "access_token": long_lived},
            )
            if me.status_code < 400:
                profile = me.json() if isinstance(me.json(), dict) else {}
                username = str(profile.get("username") or profile.get("name") or "")
                ig_id = str(profile.get("user_id") or profile.get("id") or user_id)
        except Exception as exc:
            logger.warning("InstagramOAuth.me_failed | error={error}", error=str(exc))

    return {
        "access_token": long_lived,
        "ig_user_id": ig_id,
        "username": username,
    }
