"""Wazzup24 MessagingAdapter — tenant API key, channels in metadata, no OAuth.

WhatsApp in MVP is exclusively this adapter (Wazzup channel). Meta Cloud API is not used.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from loguru import logger

from app.core.config import resolve_webhook_base_url, settings
from app.services.integration_hub.http import hub_request
from app.services.integration_hub.messaging import MessageReceived
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle

WAZZUP_API_BASE = (getattr(settings, "WAZZUP_API_BASE_URL", None) or "https://api.wazzup24.com/v3").rstrip("/")

_TRANSPORT_KIND = {
    "whatsapp": "whatsapp",
    "wapi": "whatsapp",
    "telegram": "telegram",
    "tgapi": "telegram",
    "instagram": "instagram",
}

_KIND_CHAT_TYPE = {
    "whatsapp": "whatsapp",
    "telegram": "telegram",
    "instagram": "instagram",
}


def wazzup_webhook_public_url(connection_id: UUID) -> str:
    """Public URI registered with Wazzup (max 200 chars). Spec: /webhooks/wazzup/:id."""
    return f"{resolve_webhook_base_url()}/webhooks/wazzup/{connection_id}"


def summarize_wazzup_channels(raw: Any) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    if isinstance(raw, dict):
        inner = raw.get("channels") or raw.get("data") or []
        rows = inner if isinstance(inner, list) else []
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        transport = str(item.get("transport") or "").strip().lower()
        channel_id = str(item.get("channelId") or item.get("id") or "").strip()
        if not channel_id:
            continue
        out.append(
            {
                "channel_id": channel_id,
                "transport": transport,
                "kind": _TRANSPORT_KIND.get(transport, transport or "unknown"),
                "plain_id": item.get("plainId") or item.get("plain_id"),
                "state": item.get("state"),
            }
        )
    return out


class WazzupHubAdapter:
    """MessagingAdapter: API key form, list channels, register webhook, send/parse."""

    provider = "wazzup"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _base(self, secrets: TokenBundle | None = None) -> str:
        extra = (secrets.extra if secrets else {}) or {}
        return str(extra.get("base_url") or WAZZUP_API_BASE).rstrip("/")

    def _default_channel_id(self, secrets: TokenBundle) -> str:
        extra = secrets.extra or {}
        if extra.get("channel_id"):
            return str(extra["channel_id"])
        channels = extra.get("channels") or (extra.get("metadata") or {}).get("channels") or []
        if isinstance(channels, list):
            for row in channels:
                if isinstance(row, dict) and row.get("channel_id") and row.get("state") == "active":
                    return str(row["channel_id"])
            for row in channels:
                if isinstance(row, dict) and row.get("channel_id"):
                    return str(row["channel_id"])
        return ""

    def _chat_type(self, secrets: TokenBundle, channel_id: str, override: str | None) -> str:
        if override:
            return _KIND_CHAT_TYPE.get(override.lower(), override.lower())
        channels = (secrets.extra or {}).get("channels") or []
        if isinstance(channels, list):
            for row in channels:
                if isinstance(row, dict) and str(row.get("channel_id")) == channel_id:
                    kind = str(row.get("kind") or row.get("transport") or "whatsapp")
                    return _KIND_CHAT_TYPE.get(kind, "whatsapp")
        return "whatsapp"

    async def connect(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        payload: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        _ = platform_app
        api_key = str(
            payload.get("api_key")
            or payload.get("client_access_token")
            or payload.get("token")
            or ""
        ).strip()
        if len(api_key) < 8:
            raise ValueError("Для Wazzup нужен API Key (client_access_token).")
        base = self._base()
        response = await http.get(
            f"{base}/channels",
            headers=self._headers(api_key),
            timeout=15.0,
        )
        if response.status_code in {401, 403}:
            raise ValueError("API-ключ Wazzup отклонён.")
        response.raise_for_status()
        try:
            raw_channels = response.json()
        except Exception:
            raw_channels = []
        channels = summarize_wazzup_channels(raw_channels)
        preferred = str(payload.get("channel_id") or payload.get("reference_id") or "").strip()
        if preferred and channels and not any(row["channel_id"] == preferred for row in channels):
            raise ValueError("Указанный Channel ID не найден в аккаунте Wazzup.")
        account_id = preferred or (str(channels[0]["channel_id"]) if channels else "wazzup")
        extra: dict[str, Any] = {
            "base_url": base,
            "channels": channels,
            "metadata": {"channels": channels},
            "auth_mode": "api_key",
        }
        if preferred:
            extra["channel_id"] = preferred
        return TokenBundle(
            api_key=api_key,
            extra=extra,
            external_account_id=account_id,
        )

    async def test_connection(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
    ) -> bool:
        _ = connection_id
        api_key = secrets.api_key or ""
        if len(api_key) < 8:
            return False
        response = await http.get(
            f"{self._base(secrets)}/channels",
            headers=self._headers(api_key),
            timeout=15.0,
        )
        if response.status_code in {401, 403}:
            return False
        return 200 <= response.status_code < 400

    async def refresh(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        _ = platform_app, http
        return secrets

    async def bind_event_handlers(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
    ) -> str:
        api_key = secrets.api_key or ""
        if not api_key:
            raise ValueError("Wazzup API key is missing.")
        uri = wazzup_webhook_public_url(connection_id)
        if len(uri) > 200:
            raise ValueError("Wazzup webhooksUri must be ≤ 200 characters.")
        response = await http.patch(
            f"{self._base(secrets)}/webhooks",
            headers=self._headers(api_key),
            json={
                "webhooksUri": uri,
                "subscriptions": {
                    "messagesAndStatuses": True,
                    "channelsUpdates": True,
                    "contactsAndDealsCreation": False,
                    "templateStatus": False,
                },
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            logger.warning(
                "Wazzup.webhook_register_failed | status={status}",
                status=response.status_code,
            )
            response.raise_for_status()
        secrets.extra["webhook_uri"] = uri
        secrets.extra["webhook_registered"] = True
        return uri

    def parse_incoming_webhook(
        self,
        payload: dict[str, Any],
        *,
        connection_id: UUID | None = None,
    ) -> list[MessageReceived]:
        """Normalize Wazzup JSON into architecture §4 ``message.received`` events."""
        if not isinstance(payload, dict):
            return []
        if payload.get("test") is True:
            return []
        raw_items = payload.get("messages")
        if isinstance(raw_items, list):
            items = raw_items
        elif isinstance(payload.get("message"), dict):
            items = [payload["message"]]
        else:
            items = []
        events: list[MessageReceived] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            is_echo = bool(item.get("isEcho") is True or item.get("isOutbound") is True)
            status = str(item.get("status") or "").lower()
            if status in {"sent", "delivered", "read"} and not item.get("text"):
                continue
            chat_id = str(item.get("chatId") or item.get("chat_id") or "").strip()
            text = str(item.get("text") or item.get("message") or "").strip()
            content_uri = str(item.get("contentUri") or "") or None
            if not chat_id or (not text and not content_uri):
                continue
            if is_echo:
                continue
            contact = item.get("contact") if isinstance(item.get("contact"), dict) else {}
            chat_type = str(item.get("chatType") or "whatsapp").lower()
            kind = _TRANSPORT_KIND.get(chat_type, chat_type)
            events.append(
                MessageReceived(
                    type="message.received",
                    provider="wazzup",
                    connection_id=str(connection_id) if connection_id else None,
                    channel_id=str(item.get("channelId") or item.get("channel_id") or ""),
                    channel_type=kind,
                    chat_id=chat_id,
                    message_id=str(item.get("messageId") or item.get("message_id") or ""),
                    text=text,
                    content_uri=content_uri,
                    from_id=str(contact.get("phone") or contact.get("username") or chat_id),
                    from_name=str(contact.get("name") or item.get("authorName") or chat_id),
                    timestamp=str(item.get("dateTime") or ""),
                    is_echo=False,
                    raw=item,
                )
            )
        return events

    async def send_message(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        chat_id: str,
        text: str,
        channel_id: str | None = None,
        channel_type: str | None = None,
    ) -> dict[str, Any]:
        """Outbound via the tenant ``client_access_token`` (API key), never a platform secret."""
        api_key = secrets.api_key or ""
        if not api_key:
            raise ValueError("Wazzup client_access_token is missing.")
        cid = (channel_id or self._default_channel_id(secrets)).strip()
        if not cid:
            raise ValueError("Wazzup channelId is required to send a message.")
        chat_type = self._chat_type(secrets, cid, channel_type)
        body = {
            "channelId": cid,
            "chatType": chat_type,
            "chatId": chat_id,
            "text": (text or "")[:4096],
        }
        response = await hub_request(
            http,
            connection_id=connection_id,
            method="POST",
            url=f"{self._base(secrets)}/message",
            json_body=body,
            headers=self._headers(api_key),
        )
        try:
            parsed = response.json()
        except Exception:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {"result": parsed}

    async def request(
        self,
        *,
        connection_id: UUID,
        secrets: TokenBundle,
        method: str,
        url: str,
        http: httpx.AsyncClient,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {}
        if secrets.api_key:
            headers["Authorization"] = f"Bearer {secrets.api_key}"
        return await hub_request(
            http,
            connection_id=connection_id,
            method=method,
            url=url,
            json_body=json_body,
            params=params,
            headers=headers,
        )
