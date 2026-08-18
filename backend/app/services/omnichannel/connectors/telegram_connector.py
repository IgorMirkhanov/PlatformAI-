"""Telegram Bot API Omnichannel connector."""

from __future__ import annotations

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


class TelegramAPIError(ChannelConnectorError):
    """Telegram Bot API failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, channel="telegram", cause=cause)
        self.status_code = status_code


class TelegramAuthError(TelegramAPIError):
    """Invalid or missing bot token."""


class TelegramForbiddenError(TelegramAPIError):
    """Bot blocked by user / chat not found / no rights."""


@ChannelRegistry.register("telegram")
class TelegramConnector(BaseChannelConnector):
    """
    Telegram Bot API adapter.

    Maps Update JSON ↔ InboundMessage / OutboundMessage so CRM and Flow Builder
    never depend on Telegram-specific payload shapes.
    """

    channel_id = "telegram"

    def __init__(
        self,
        *,
        organization_id: uuid.UUID | None = None,
        bot_token: str | None = None,
        api_base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20.0,
        default_parse_mode: str | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.bot_token = (
            bot_token
            if bot_token is not None
            else getattr(settings, "TELEGRAM_DEFAULT_BOT_TOKEN", None)
        )
        self.api_base_url = (
            api_base_url
            if api_base_url is not None
            else (
                getattr(settings, "TELEGRAM_API_BASE_URL", None)
                or getattr(settings, "TELEGRAM_API_BASE", None)
                or "https://api.telegram.org"
            )
        ).rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.default_parse_mode = default_parse_mode
        self._http_client = http_client

    def _api_url(self, method: str) -> str:
        token = (self.bot_token or "").strip()
        if not token:
            raise TelegramAuthError(
                "TELEGRAM_DEFAULT_BOT_TOKEN is not configured.",
                status_code=401,
            )
        return f"{self.api_base_url}/bot{token}/{method}"

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def parse_all_inbound(self, raw_data: dict[str, Any]) -> list[InboundMessage]:
        """Parse a Telegram Update into zero or one InboundMessage."""
        if not isinstance(raw_data, dict):
            return []
        org_id = self.organization_id
        if org_id is None:
            raise ChannelConnectorError(
                "organization_id is required to parse Telegram webhooks.",
                channel="telegram",
            )

        inbound = self._map_update(raw_data, organization_id=org_id)
        return [inbound] if inbound is not None else []

    async def parse_webhook(self, raw_data: dict[str, Any]) -> InboundMessage:
        messages = self.parse_all_inbound(raw_data)
        if not messages:
            raise ChannelConnectorError(
                "No inbound Telegram message found in Update payload.",
                channel="telegram",
            )
        return messages[0]

    def _map_update(
        self,
        update: dict[str, Any],
        *,
        organization_id: uuid.UUID,
    ) -> InboundMessage | None:
        if "callback_query" in update and isinstance(update["callback_query"], dict):
            return self._map_callback_query(
                update["callback_query"],
                organization_id=organization_id,
                raw_payload=update,
            )

        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
            or update.get("edited_channel_post")
            or update.get("business_message")
            or update.get("edited_business_message")
        )
        if not isinstance(message, dict):
            return None
        return self._map_message(
            message,
            organization_id=organization_id,
            raw_payload=update,
        )

    def _map_callback_query(
        self,
        cq: dict[str, Any],
        *,
        organization_id: uuid.UUID,
        raw_payload: dict[str, Any],
    ) -> InboundMessage | None:
        message = cq.get("message") if isinstance(cq.get("message"), dict) else {}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        from_user = cq.get("from") if isinstance(cq.get("from"), dict) else {}
        chat_id = str(chat.get("id") or from_user.get("id") or "").strip()
        if not chat_id:
            return None
        data = str(cq.get("data") or "")
        return InboundMessage(
            channel="telegram",
            channel_message_id=str(cq.get("id") or uuid.uuid4()),
            organization_id=organization_id,
            sender_id=chat_id,
            sender_name=self._display_name(from_user),
            content=data or "[callback_query]",
            media_urls=[],
            raw_payload=raw_payload,
            timestamp=self._message_timestamp(message),
        )

    def _map_message(
        self,
        message: dict[str, Any],
        *,
        organization_id: uuid.UUID,
        raw_payload: dict[str, Any],
    ) -> InboundMessage | None:
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_id = str(chat.get("id") or "").strip()
        if not chat_id:
            return None

        from_user = message.get("from") if isinstance(message.get("from"), dict) else {}
        message_id = str(message.get("message_id") or uuid.uuid4())
        content, media_urls = self._extract_content_and_media(message)

        return InboundMessage(
            channel="telegram",
            channel_message_id=message_id,
            organization_id=organization_id,
            sender_id=chat_id,
            sender_name=self._display_name(from_user),
            content=content,
            media_urls=media_urls,
            raw_payload=raw_payload,
            timestamp=self._message_timestamp(message),
        )

    @staticmethod
    def _display_name(from_user: dict[str, Any]) -> str | None:
        first = str(from_user.get("first_name") or "").strip()
        last = str(from_user.get("last_name") or "").strip()
        username = str(from_user.get("username") or "").strip()
        full = " ".join(p for p in (first, last) if p).strip()
        if full:
            return full
        return username or None

    @staticmethod
    def _message_timestamp(message: dict[str, Any]) -> datetime:
        try:
            return datetime.fromtimestamp(int(message.get("date")), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return datetime.now(timezone.utc)

    @staticmethod
    def _extract_content_and_media(message: dict[str, Any]) -> tuple[str, list[str]]:
        media_urls: list[str] = []
        if "text" in message:
            return str(message.get("text") or ""), media_urls
        if "caption" in message or any(
            k in message
            for k in ("photo", "video", "document", "audio", "voice", "sticker", "animation")
        ):
            caption = str(message.get("caption") or "")
            if "photo" in message and isinstance(message["photo"], list) and message["photo"]:
                largest = message["photo"][-1]
                file_id = largest.get("file_id") if isinstance(largest, dict) else None
                if file_id:
                    media_urls.append(f"telegram-file://{file_id}")
                return caption or "[photo]", media_urls
            for kind in ("video", "document", "audio", "voice", "sticker", "animation"):
                blob = message.get(kind)
                if isinstance(blob, dict) and blob.get("file_id"):
                    media_urls.append(f"telegram-file://{blob['file_id']}")
                    name = blob.get("file_name") or blob.get("file_unique_id") or kind
                    return caption or f"[{kind}:{name}]", media_urls
            return caption or "[media]", media_urls
        if "location" in message and isinstance(message["location"], dict):
            loc = message["location"]
            return (
                f"[location] lat={loc.get('latitude')} lon={loc.get('longitude')}",
                media_urls,
            )
        if "contact" in message and isinstance(message["contact"], dict):
            contact = message["contact"]
            return (
                f"[contact] {contact.get('first_name') or ''} {contact.get('phone_number') or ''}".strip(),
                media_urls,
            )
        return "[unsupported]", media_urls

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send_message(self, message: OutboundMessage) -> bool:
        if message.channel not in {"telegram"}:
            raise ChannelConnectorError(
                f"TelegramConnector cannot send channel='{message.channel}'.",
                channel="telegram",
            )

        if message.media_urls:
            return await self._send_photo_or_document(message)
        return await self._send_text(message)

    async def _send_text(self, message: OutboundMessage) -> bool:
        url = self._api_url("sendMessage")
        payload: dict[str, Any] = {
            "chat_id": message.recipient_id,
            "text": (message.content or "")[:4096],
        }
        parse_mode = message.parse_mode or self.default_parse_mode
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if message.reply_to_message_id:
            try:
                payload["reply_to_message_id"] = int(message.reply_to_message_id)
            except (TypeError, ValueError):
                payload["reply_to_message_id"] = message.reply_to_message_id
        await self._post_json(url, payload)
        return True

    async def _send_photo_or_document(self, message: OutboundMessage) -> bool:
        media_url = (message.media_urls or [None])[0]
        if not media_url:
            return await self._send_text(message)

        is_document = any(
            str(media_url).lower().endswith(ext)
            for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")
        )
        method = "sendDocument" if is_document else "sendPhoto"
        field = "document" if is_document else "photo"
        url = self._api_url(method)
        payload: dict[str, Any] = {
            "chat_id": message.recipient_id,
            field: media_url,
        }
        if message.content:
            payload["caption"] = message.content[:1024]
            parse_mode = message.parse_mode or self.default_parse_mode
            if parse_mode:
                payload["parse_mode"] = parse_mode
        await self._post_json(url, payload)
        return True

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._http_client
        owns_client = client is None
        try:
            if client is None:
                client = httpx.AsyncClient(timeout=self.timeout_seconds)
            response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise TelegramAPIError("Telegram Bot API request timed out.", cause=exc) from exc
        except httpx.HTTPError as exc:
            raise TelegramAPIError(
                f"Telegram Bot API connection error: {exc}",
                cause=exc,
            ) from exc
        finally:
            if owns_client and client is not None:
                await client.aclose()

        if response.status_code >= 400:
            raise self._translate_http_error(response)

        try:
            body = response.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and body.get("ok") is False:
            raise self._translate_api_error(body, http_status=response.status_code)

        logger.info(
            "Telegram.send_ok | chat_id={chat_id}",
            chat_id=payload.get("chat_id"),
        )
        return body if isinstance(body, dict) else {}

    def _translate_http_error(self, response: httpx.Response) -> TelegramAPIError:
        detail = response.text[:500]
        description = None
        error_code = None
        try:
            body = response.json()
            if isinstance(body, dict):
                description = body.get("description")
                error_code = body.get("error_code")
                detail = str(description or detail)
        except Exception:
            pass
        return self._map_error(
            detail,
            http_status=int(response.status_code),
            error_code=error_code,
        )

    def _translate_api_error(
        self,
        body: dict[str, Any],
        *,
        http_status: int,
    ) -> TelegramAPIError:
        detail = str(body.get("description") or "Telegram API error")
        return self._map_error(
            detail,
            http_status=http_status,
            error_code=body.get("error_code"),
        )

    @staticmethod
    def _map_error(
        detail: str,
        *,
        http_status: int,
        error_code: Any,
    ) -> TelegramAPIError:
        code = int(error_code) if error_code is not None else http_status
        lowered = detail.lower()
        if code == 401 or "unauthorized" in lowered:
            return TelegramAuthError(detail, status_code=code)
        if (
            code == 403
            or "bot was blocked" in lowered
            or "chat not found" in lowered
            or "forbidden" in lowered
        ):
            return TelegramForbiddenError(detail, status_code=code)
        return TelegramAPIError(detail, status_code=code)
