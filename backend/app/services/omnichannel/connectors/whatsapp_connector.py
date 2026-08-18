"""WhatsApp Cloud API (Meta Graph) Omnichannel connector."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings
from app.schemas.omnichannel.message import InboundMessage, OutboundMessage
from app.services.omnichannel.base_connector import (
    BaseChannelConnector,
    ChannelConnectorError,
    ChannelRegistry,
)


class WhatsAppAPIError(ChannelConnectorError):
    """Meta Graph / WhatsApp Cloud API failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, channel="whatsapp", cause=cause)
        self.status_code = status_code


class WhatsAppAuthError(WhatsAppAPIError):
    """Invalid or missing access token / permissions."""


class WhatsAppRateLimitError(WhatsAppAPIError):
    """Meta rate limit / capacity error."""


@ChannelRegistry.register("whatsapp")
class WhatsAppConnector(BaseChannelConnector):
    """
    Meta WhatsApp Cloud API adapter.

    Maps Cloud API webhooks ↔ InboundMessage / OutboundMessage so CRM and
    Flow Builder never touch Graph payloads.
    """

    channel_id = "whatsapp"

    def __init__(
        self,
        *,
        organization_id: uuid.UUID | None = None,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        verify_token: str | None = None,
        api_version: str | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.organization_id = organization_id
        self.access_token = (
            access_token
            if access_token is not None
            else getattr(settings, "WHATSAPP_ACCESS_TOKEN", None)
        )
        self.phone_number_id = (
            phone_number_id
            if phone_number_id is not None
            else getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None)
        )
        self.verify_token = (
            verify_token
            if verify_token is not None
            else getattr(settings, "WHATSAPP_VERIFY_TOKEN", None)
        )
        self.api_version = (
            api_version or getattr(settings, "WHATSAPP_API_VERSION", None) or "v18.0"
        ).strip()
        self.base_url = (
            base_url or getattr(settings, "WHATSAPP_BASE_URL", None) or "https://graph.facebook.com"
        ).rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Webhook verification (Meta GET hub.*)
    # ------------------------------------------------------------------

    def verify_webhook(
        self,
        *,
        hub_mode: str,
        hub_verify_token: str,
        hub_challenge: str,
    ) -> str | None:
        """
        Validate Meta webhook subscription handshake.

        Returns the challenge string on success, otherwise ``None``.
        """
        expected = (self.verify_token or "").strip()
        if not expected:
            logger.warning("WhatsApp.verify_webhook | WHATSAPP_VERIFY_TOKEN is not configured")
            return None
        if hub_mode != "subscribe":
            return None
        if not hub_challenge:
            return None
        if not secrets.compare_digest(str(hub_verify_token), expected):
            logger.warning("WhatsApp.verify_webhook | token mismatch")
            return None
        return str(hub_challenge)

    @staticmethod
    def verify_webhook_static(
        *,
        hub_mode: str,
        hub_verify_token: str,
        hub_challenge: str,
        expected_token: str | None = None,
    ) -> str | None:
        """Platform-level verify using settings (or explicit token)."""
        connector = WhatsAppConnector(verify_token=expected_token)
        return connector.verify_webhook(
            hub_mode=hub_mode,
            hub_verify_token=hub_verify_token,
            hub_challenge=hub_challenge,
        )

    # ------------------------------------------------------------------
    # Inbound parsing
    # ------------------------------------------------------------------

    def parse_all_inbound(self, raw_data: dict[str, Any]) -> list[InboundMessage]:
        """Extract all user messages from a Cloud API webhook payload."""
        if not isinstance(raw_data, dict):
            return []
        if raw_data.get("object") not in {None, "whatsapp_business_account"}:
            # Allow missing object for tests / partial payloads; reject wrong objects.
            if raw_data.get("object") is not None:
                logger.debug(
                    "WhatsApp.parse | ignoring object={obj}",
                    obj=raw_data.get("object"),
                )
                return []

        org_id = self.organization_id
        if org_id is None:
            raise ChannelConnectorError(
                "organization_id is required to parse WhatsApp webhooks.",
                channel="whatsapp",
            )

        messages: list[InboundMessage] = []
        for entry in raw_data.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes") or []:
                if not isinstance(change, dict):
                    continue
                value = change.get("value") if isinstance(change.get("value"), dict) else {}
                contacts = {
                    str(c.get("wa_id")): c
                    for c in (value.get("contacts") or [])
                    if isinstance(c, dict) and c.get("wa_id")
                }
                for msg in value.get("messages") or []:
                    if not isinstance(msg, dict):
                        continue
                    inbound = self._map_cloud_message(
                        msg,
                        contacts=contacts,
                        organization_id=org_id,
                        raw_payload=raw_data,
                    )
                    if inbound is not None:
                        messages.append(inbound)
        return messages

    async def parse_webhook(self, raw_data: dict[str, Any]) -> InboundMessage:
        messages = self.parse_all_inbound(raw_data)
        if not messages:
            raise ChannelConnectorError(
                "No inbound WhatsApp messages found in webhook payload.",
                channel="whatsapp",
            )
        return messages[0]

    def _map_cloud_message(
        self,
        msg: dict[str, Any],
        *,
        contacts: dict[str, Any],
        organization_id: uuid.UUID,
        raw_payload: dict[str, Any],
    ) -> InboundMessage | None:
        msg_type = str(msg.get("type") or "text")
        sender_id = str(msg.get("from") or "").strip()
        if not sender_id:
            return None
        channel_message_id = str(msg.get("id") or "").strip() or str(uuid.uuid4())

        contact = contacts.get(sender_id) or {}
        profile = contact.get("profile") if isinstance(contact.get("profile"), dict) else {}
        sender_name = str(profile.get("name") or "") or None

        content = ""
        media_urls: list[str] = []

        if msg_type == "text":
            text_body = msg.get("text") if isinstance(msg.get("text"), dict) else {}
            content = str(text_body.get("body") or "")
        elif msg_type in {"image", "video", "audio", "document", "sticker"}:
            media = msg.get(msg_type) if isinstance(msg.get(msg_type), dict) else {}
            media_id = media.get("id")
            link = media.get("link")
            if link:
                media_urls.append(str(link))
            elif media_id:
                # Graph media id — callers may resolve via /{media_id}; store as marker.
                media_urls.append(f"whatsapp-media://{media_id}")
            content = str(media.get("caption") or media.get("filename") or f"[{msg_type}]")
        elif msg_type == "location":
            loc = msg.get("location") if isinstance(msg.get("location"), dict) else {}
            content = (
                f"[location] lat={loc.get('latitude')} lon={loc.get('longitude')} "
                f"{loc.get('name') or ''} {loc.get('address') or ''}".strip()
            )
        elif msg_type == "contacts":
            content = "[contacts]"
        elif msg_type == "button":
            button = msg.get("button") if isinstance(msg.get("button"), dict) else {}
            content = str(button.get("text") or button.get("payload") or "")
        elif msg_type == "interactive":
            interactive = msg.get("interactive") if isinstance(msg.get("interactive"), dict) else {}
            reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
            if isinstance(reply, dict):
                content = str(reply.get("title") or reply.get("id") or "")
            else:
                content = "[interactive]"
        else:
            content = f"[{msg_type}]"

        ts_raw = msg.get("timestamp")
        try:
            timestamp = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            timestamp = datetime.now(timezone.utc)

        return InboundMessage(
            channel="whatsapp",
            channel_message_id=channel_message_id,
            organization_id=organization_id,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            media_urls=media_urls,
            raw_payload=raw_payload,
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------
    # Outbound send
    # ------------------------------------------------------------------

    def _messages_url(self) -> str:
        phone_id = (self.phone_number_id or "").strip()
        if not phone_id:
            raise WhatsAppAuthError(
                "WHATSAPP_PHONE_NUMBER_ID is not configured.",
                status_code=401,
            )
        return f"{self.base_url}/{self.api_version}/{phone_id}/messages"

    def _auth_headers(self) -> dict[str, str]:
        token = (self.access_token or "").strip()
        if not token:
            raise WhatsAppAuthError(
                "WHATSAPP_ACCESS_TOKEN is not configured.",
                status_code=401,
            )
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _build_outbound_payload(self, message: OutboundMessage) -> dict[str, Any]:
        to = message.recipient_id.strip()
        if message.template_name:
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": message.template_name,
                    "language": {"code": message.template_language or "en_US"},
                },
            }
            if message.template_components:
                payload["template"]["components"] = message.template_components
            return payload

        if message.media_urls:
            url = message.media_urls[0]
            # Default to image link; document if looks like a file path with extension.
            kind = "document" if any(
                url.lower().endswith(ext) for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx")
            ) else "image"
            body: dict[str, Any] = {"link": url}
            if message.content and kind in {"image", "document", "video"}:
                body["caption"] = message.content[:1024]
            return {
                "messaging_product": "whatsapp",
                "to": to,
                "type": kind,
                kind: body,
            }

        text_payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": (message.content or "")[:4096]},
        }
        if message.reply_to_message_id:
            text_payload["context"] = {"message_id": message.reply_to_message_id}
        return text_payload

    async def send_message(self, message: OutboundMessage) -> bool:
        if message.channel not in {"whatsapp", "whatsapp_cloud"}:
            raise ChannelConnectorError(
                f"WhatsAppConnector cannot send channel='{message.channel}'.",
                channel="whatsapp",
            )
        url = self._messages_url()
        headers = self._auth_headers()
        payload = self._build_outbound_payload(message)

        client = self._http_client
        owns_client = client is None
        try:
            if client is None:
                client = httpx.AsyncClient(timeout=self.timeout_seconds)
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise WhatsAppAPIError(
                "WhatsApp Cloud API request timed out.",
                cause=exc,
            ) from exc
        except httpx.HTTPError as exc:
            raise WhatsAppAPIError(
                f"WhatsApp Cloud API connection error: {exc}",
                cause=exc,
            ) from exc
        finally:
            if owns_client and client is not None:
                await client.aclose()

        if response.status_code >= 400:
            raise self._translate_http_error(response)

        logger.info(
            "WhatsApp.send_ok | to={to} type={type}",
            to=message.recipient_id,
            type=payload.get("type"),
        )
        return True

    def _translate_http_error(self, response: httpx.Response) -> WhatsAppAPIError:
        detail = response.text[:500]
        code = None
        try:
            body = response.json()
            err = body.get("error") if isinstance(body, dict) else {}
            if isinstance(err, dict):
                detail = str(err.get("message") or detail)
                code = err.get("code")
        except Exception:
            pass

        status = int(response.status_code)
        if status in {401, 403}:
            return WhatsAppAuthError(detail, status_code=status)
        if status == 429 or code in {4, 80007, 130429}:
            return WhatsAppRateLimitError(detail, status_code=status)
        return WhatsAppAPIError(detail, status_code=status)
