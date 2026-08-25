"""Cheap provider pings before persisting BYOK secrets."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.models.tenant_credentials import CredentialKind


class CredentialValidationError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _secret(payload: dict[str, Any]) -> str:
    return str(
        payload.get("api_key")
        or payload.get("token")
        or payload.get("bot_token")
        or payload.get("access_token")
        or ""
    ).strip()


async def validate_credential_payload(kind: str, payload: dict[str, Any]) -> None:
    key = (kind or "").strip().lower()
    secret = _secret(payload if isinstance(payload, dict) else {})
    timeout = httpx.Timeout(12.0, connect=5.0)

    if key == CredentialKind.LLM_OPENAI.value:
        if not secret:
            raise CredentialValidationError("OpenAI API key is required.")
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {secret}"},
            )
        if response.status_code >= 400:
            raise CredentialValidationError(
                f"OpenAI rejected the key (HTTP {response.status_code}).",
                status_code=400,
            )
        return

    if key == CredentialKind.CHANNEL_TELEGRAM.value:
        if not secret:
            raise CredentialValidationError("Telegram bot token is required.")
        base = getattr(settings, "TELEGRAM_API_BASE", "https://api.telegram.org")
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base}/bot{secret}/getMe")
        data = {}
        try:
            data = response.json()
        except Exception:
            data = {}
        if response.status_code >= 400 or not data.get("ok"):
            description = data.get("description") if isinstance(data, dict) else None
            raise CredentialValidationError(
                str(description or f"Telegram getMe failed (HTTP {response.status_code})."),
                status_code=400,
            )
        return

    if not secret and key.startswith("llm_"):
        raise CredentialValidationError("API key is required for this provider.")
