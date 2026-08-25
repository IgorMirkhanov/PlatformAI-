from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import encrypt_credential, hash_bot_token
from app.models.core_models import Bot, BotFlow, DiagnosticErrorType, PlatformType
from app.models.users import User
from app.schemas.core_schemas import (
    TelegramSetupRequest,
    TelegramSetupResponse,
)
from app.schemas.webhook_schemas import ParsedTelegramInbound, TelegramUpdate
from app.services.diagnostic_log_service import diagnostic_log_service
from app.services.messenger_errors import (
    MessengerAPIError,
    format_messenger_diagnostic,
    messenger_error_is_retriable,
)
from app.services.webhook_service import process_inbound_message


def _safe_telegram_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _friendly_telegram_webhook_error(description: object) -> str:
    text = str(description or "").strip()
    lower = text.lower()
    if any(
        token in lower
        for token in (
            "bad webhook",
            "failed to resolve host",
            "https url must be provided",
            "wrong port",
            "can be set up only on ports",
        )
    ):
        return (
            "Telegram не принимает webhook на localhost. "
            "Задайте публичный HTTPS (NGROK_TUNNEL_URL) или используйте локальный polling."
        )
    if text:
        return text
    return "Telegram отклонил регистрацию webhook."


@dataclass(frozen=True)
class TelegramInbound:
    chat_id: str
    username: str
    first_name: str
    last_name: str
    message_text: str
    content_type: str
    callback_query_id: str | None
    raw_update: dict[str, Any]


class TelegramService:
    """Telegram Bot API integration: webhook parsing, outbound dispatch, setup."""

    MEDIA_FALLBACK = (
        "I received your attachment. For guided flows please send text or use the buttons. "
        "If you're chatting with the AI agent, describe what you need and I'll help."
    )

    async def get_bot_by_token_hash(
        self,
        db: AsyncSession,
        bot_token_hash: str,
    ) -> Bot | None:
        """Resolve an active bot by webhook path secret (token hash)."""
        if not bot_token_hash:
            return None

        # Support raw Telegram tokens accidentally posted to the path.
        lookup_hash = bot_token_hash
        if ":" in bot_token_hash:
            lookup_hash = hash_bot_token(bot_token_hash)

        result = await db.execute(
            select(Bot).where(
                Bot.is_active.is_(True),
                Bot.credentials["token_hash"].as_string() == lookup_hash,
            )
        )
        bot = result.scalar_one_or_none()
        if bot is not None:
            return bot

        # Omnichannel hub: token_hash lives on BotChannel.meta_data after connect.
        try:
            from app.models.channels import BotChannel, HubChannelType

            channel_result = await db.execute(
                select(BotChannel).where(
                    BotChannel.channel_type.in_(
                        [HubChannelType.TELEGRAM, HubChannelType.TELEGRAM_BUSINESS]
                    ),
                    BotChannel.meta_data["token_hash"].as_string() == lookup_hash,
                )
            )
            channel = channel_result.scalar_one_or_none()
            if channel is not None:
                hub_bot = await db.get(Bot, channel.bot_id)
                if hub_bot is not None and bool(getattr(hub_bot, "is_active", True)):
                    return hub_bot
        except Exception as exc:
            logger.warning(
                "TelegramService.channel_token_hash_lookup_failed | error={error}",
                error=str(exc),
            )

        # Omnichannel bots may only store the hash under credentials.channels.telegram.
        result = await db.execute(select(Bot).where(Bot.is_active.is_(True)))
        for candidate in result.scalars().all():
            credentials = candidate.credentials if isinstance(candidate.credentials, dict) else {}
            if credentials.get("token_hash") == lookup_hash:
                return candidate
            channels = credentials.get("channels") if isinstance(credentials.get("channels"), dict) else {}
            for key in ("telegram", "telegram_business"):
                telegram_channel = channels.get(key) if isinstance(channels.get(key), dict) else {}
                if telegram_channel.get("token_hash") == lookup_hash:
                    return candidate
        return None

    def extract_bot_token(self, bot: Bot) -> str:
        from app.models.bot import get_telegram_bot_token

        return get_telegram_bot_token(bot)

    def extract_inbound_fields(self, update: TelegramUpdate | dict[str, Any]) -> ParsedTelegramInbound | None:
        """Extract chat_id, names, and message text from a typed or raw Telegram update."""
        if isinstance(update, dict):
            try:
                update = TelegramUpdate.model_validate(update)
            except Exception:
                inbound = self.parse_update(update)
                if inbound is None:
                    return None
                return ParsedTelegramInbound(
                    chat_id=inbound.chat_id,
                    username=inbound.username,
                    first_name=inbound.first_name,
                    last_name=inbound.last_name,
                    message_text=inbound.message_text,
                    content_type=inbound.content_type,
                    callback_query_id=inbound.callback_query_id,
                )

        inbound = self.parse_update(update.to_raw_dict())
        if inbound is None:
            return None
        return ParsedTelegramInbound(
            chat_id=inbound.chat_id,
            username=inbound.username,
            first_name=inbound.first_name,
            last_name=inbound.last_name,
            message_text=inbound.message_text,
            content_type=inbound.content_type,
            callback_query_id=inbound.callback_query_id,
        )

    def parse_update(self, update: dict[str, Any]) -> TelegramInbound | None:
        if "callback_query" in update:
            return self._parse_callback_query(update["callback_query"])

        # Telegram Business: business_message / edited_business_message
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("business_message")
            or update.get("edited_business_message")
        )
        if not message:
            if update.get("business_connection"):
                logger.info(
                    "TelegramService.business_connection | id={conn_id}",
                    conn_id=(update.get("business_connection") or {}).get("id"),
                )
            logger.debug("TelegramService.ignored_update | reason=no_supported_payload")
            return None

        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return None

        from_user = message.get("from") or {}
        username = str(from_user.get("username") or "")
        first_name = str(from_user.get("first_name") or "")
        last_name = str(from_user.get("last_name") or "")

        if "text" in message:
            return TelegramInbound(
                chat_id=chat_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                message_text=str(message["text"]),
                content_type="text",
                callback_query_id=None,
                raw_update=update,
            )

        content_type, description = self._detect_media_type(message)
        return TelegramInbound(
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            message_text=description,
            content_type=content_type,
            callback_query_id=None,
            raw_update=update,
        )

    async def handle_webhook(
        self,
        db: AsyncSession,
        bot_token_hash: str,
        update: dict[str, Any],
    ) -> None:
        """Backward-compatible direct webhook handler (used by sync simulate paths)."""
        await self.process_queued_webhook(
            db=db,
            bot_token_hash=bot_token_hash,
            update=update,
        )

    async def process_queued_webhook(
        self,
        db: AsyncSession,
        bot_token_hash: str,
        update: dict[str, Any],
    ) -> dict[str, Any]:
        bot = await self.get_bot_by_token_hash(db, bot_token_hash)
        if bot is None:
            logger.warning(
                "TelegramService.unknown_bot | token_hash={token_hash}",
                token_hash=bot_token_hash[:12],
            )
            return {"status": "ignored", "reason": "unknown_bot"}

        inbound = self.parse_update(update)
        if inbound is None:
            return {"status": "ignored", "reason": "unsupported_update"}

        try:
            bot_token = self.extract_bot_token(bot)
        except ValueError as exc:
            logger.error(
                "TelegramService.token_missing | bot_id={bot_id} error={error}",
                bot_id=bot.id,
                error=str(exc),
            )
            return {"status": "failed", "reason": "missing_token"}

        if inbound.callback_query_id:
            await self.answer_callback_query(bot_token, inbound.callback_query_id)

        try:
            on_ai_node = await self._client_on_ai_node(db, bot.id, inbound.chat_id)
            operator_paused = await self._client_paused_by_operator(db, bot.id, inbound.chat_id)

            if (
                not operator_paused
                and inbound.content_type != "text"
                and not on_ai_node
            ):
                await self.send_message(
                    bot_token=bot_token,
                    chat_id=inbound.chat_id,
                    text=self.MEDIA_FALLBACK,
                    buttons=[],
                    bot_id=bot.id,
                    db=db,
                )
                return {"status": "processed", "response_text": self.MEDIA_FALLBACK}

            display_name = " ".join(
                part for part in (inbound.first_name, inbound.last_name) if part
            ).strip() or inbound.first_name

            result = await process_inbound_message(
                db=db,
                bot_id=bot.id,
                external_id=inbound.chat_id,
                username=inbound.username,
                first_name=display_name,
                message_text=inbound.message_text,
                source="telegram",
                inbound_payload={
                    "content_type": inbound.content_type,
                    "telegram_update": inbound.raw_update,
                    "last_name": inbound.last_name,
                },
            )

            if result.bot_silent or not result.response_text:
                logger.info(
                    "TelegramService.bot_silent | chat_id={chat_id} operator_paused={paused}",
                    chat_id=inbound.chat_id,
                    paused=result.bot_silent,
                )
                return {"status": "processed", "bot_silent": True, "client_id": str(result.client_id)}

            await self.send_message(
                bot_token=bot_token,
                chat_id=inbound.chat_id,
                text=result.response_text or "…",
                buttons=[button.model_dump() for button in result.buttons],
                bot_id=bot.id,
                client_id=result.client_id,
                db=db,
            )
            if result.media_attachments:
                await self.dispatch_media_attachments(
                    bot_token=bot_token,
                    chat_id=inbound.chat_id,
                    attachments=list(result.media_attachments),
                    bot_id=bot.id,
                    client_id=result.client_id,
                    db=db,
                )
            return {
                "status": "processed",
                "client_id": str(result.client_id),
                "response_text": result.response_text,
                "media_attachments": len(result.media_attachments or []),
            }
        except MessengerAPIError:
            # Already logged to BotDiagnosticLogs (MESSENGER_API_ERROR); abort safely.
            raise
        except Exception as exc:
            logger.exception(
                "TelegramService.chat_failed | bot_id={bot_id} chat_id={chat_id} error={error}",
                bot_id=bot.id,
                chat_id=inbound.chat_id,
                error=str(exc),
            )
            try:
                await self.send_message(
                    bot_token=bot_token,
                    chat_id=inbound.chat_id,
                    text="Something went wrong. Please try again in a moment.",
                    buttons=[],
                    bot_id=bot.id,
                    db=db,
                )
            except MessengerAPIError:
                raise
            except Exception as send_exc:
                logger.error(
                    "TelegramService.fallback_send_failed | error={error}",
                    error=str(send_exc),
                )
            raise

    async def send_message(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
        buttons: list[dict[str, str]],
        *,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """POST https://api.telegram.org/bot<token>/sendMessage with chat_id + text."""
        url = f"{settings.TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4096],
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": button["text"][:64], "callback_data": button["text"][:64]}]
                    for button in buttons
                ],
            }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code >= 400:
                    await self._raise_messenger_failure(
                        status_code=response.status_code,
                        body=response.text,
                        bot_id=bot_id,
                        client_id=client_id,
                        db=db,
                    )
        except MessengerAPIError:
            raise
        except httpx.HTTPError as exc:
            await self._raise_messenger_failure(
                status_code=None,
                body=str(exc),
                bot_id=bot_id,
                client_id=client_id,
                db=db,
            )

        logger.info(
            "TelegramService.sent | chat_id={chat_id} buttons={button_count}",
            chat_id=chat_id,
            button_count=len(buttons),
        )

    async def send_photo(
        self,
        bot_token: str,
        chat_id: str,
        photo_url: str,
        *,
        caption: str | None = None,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> None:
        url = f"{settings.TELEGRAM_API_BASE}/bot{bot_token}/sendPhoto"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo_url,
        }
        if caption:
            payload["caption"] = caption[:1024]
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code >= 400:
                await self._raise_messenger_failure(
                    status_code=response.status_code,
                    body=response.text,
                    bot_id=bot_id,
                    client_id=client_id,
                    db=db,
                )

    async def send_document(
        self,
        bot_token: str,
        chat_id: str,
        document_url: str,
        *,
        caption: str | None = None,
        filename: str | None = None,
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> None:
        url = f"{settings.TELEGRAM_API_BASE}/bot{bot_token}/sendDocument"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "document": document_url,
        }
        if caption:
            payload["caption"] = caption[:1024]
        if filename:
            # Telegram ignores remote filename for URL uploads; keep for diagnostics.
            payload["caption"] = (payload.get("caption") or filename)[:1024]
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code >= 400:
                await self._raise_messenger_failure(
                    status_code=response.status_code,
                    body=response.text,
                    bot_id=bot_id,
                    client_id=client_id,
                    db=db,
                )

    async def dispatch_media_attachments(
        self,
        *,
        bot_token: str,
        chat_id: str,
        attachments: list[Any],
        bot_id: uuid.UUID | None = None,
        client_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> None:
        """Deliver RAG/LLM media safely — never abort the parent webhook on failure."""
        from app.schemas.media_schemas import MediaAttachment
        from app.services.media_dispatch_service import deliver_attachments_safely

        normalized: list[MediaAttachment] = []
        for item in attachments:
            if isinstance(item, MediaAttachment):
                normalized.append(item)
            else:
                try:
                    normalized.append(MediaAttachment.model_validate(item))
                except Exception:
                    continue

        async def _send_one(attachment: MediaAttachment) -> None:
            if attachment.media_type == "image":
                await self.send_photo(
                    bot_token,
                    chat_id,
                    attachment.url,
                    caption=attachment.caption,
                    bot_id=bot_id,
                    client_id=client_id,
                    db=db,
                )
            else:
                await self.send_document(
                    bot_token,
                    chat_id,
                    attachment.url,
                    caption=attachment.caption,
                    filename=attachment.filename,
                    bot_id=bot_id,
                    client_id=client_id,
                    db=db,
                )

        await deliver_attachments_safely(
            normalized,
            send_fn=_send_one,
            bot_id=bot_id,
            client_id=client_id,
            db=db,
        )

    async def _raise_messenger_failure(
        self,
        *,
        status_code: int | None,
        body: str,
        bot_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        db: AsyncSession | None,
    ) -> None:
        detail = format_messenger_diagnostic(
            channel="Telegram",
            status_code=status_code,
            body=body,
        )
        logger.error(
            "TelegramService.send_failed | status={status} body={body}",
            status=status_code,
            body=(body or "")[:500],
        )
        if bot_id is not None:
            try:
                if db is not None:
                    await diagnostic_log_service.log(
                        db,
                        bot_id=bot_id,
                        client_id=client_id,
                        error_type=DiagnosticErrorType.MESSENGER_API_ERROR,
                        error_message=detail,
                    )
                else:
                    diagnostic_log_service.schedule_log(
                        bot_id=bot_id,
                        client_id=client_id,
                        error_type=DiagnosticErrorType.MESSENGER_API_ERROR,
                        error_message=detail,
                    )
            except Exception as log_exc:
                logger.exception(
                    "TelegramService.diagnostic_log_failed | error={error}",
                    error=str(log_exc),
                )
        raise MessengerAPIError(
            channel="telegram",
            status_code=status_code,
            detail=detail,
            retriable=messenger_error_is_retriable(status_code),
        )

    async def answer_callback_query(self, bot_token: str, callback_query_id: str) -> None:
        url = f"{settings.TELEGRAM_API_BASE}/bot{bot_token}/answerCallbackQuery"
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={"callback_query_id": callback_query_id})

    async def verify_bot_token(self, bot_token: str) -> dict[str, Any]:
        url = f"{settings.TELEGRAM_API_BASE}/bot{bot_token}/getMe"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url)
        except httpx.TimeoutException as exc:
            raise TimeoutError("Connection timed out. Please check your token.") from exc
        except httpx.HTTPError as exc:
            raise ValueError("Не удалось связаться с Telegram API.") from exc

        data = _safe_telegram_json(response)
        if response.status_code >= 400 or not data.get("ok"):
            raise ValueError(str(data.get("description") or "Недействительный токен Telegram."))

        return data.get("result", {}) if isinstance(data.get("result"), dict) else {}

    def telegram_delivery_mode(self, webhook_url: str | None = None) -> str:
        from app.core.config import is_public_https_webhook_url, resolve_webhook_base_url

        url = (webhook_url or "").strip() or f"{resolve_webhook_base_url()}/"
        return "webhook" if is_public_https_webhook_url(url) else "polling"

    async def delete_webhook(self, bot_token: str) -> None:
        url = f"{settings.TELEGRAM_API_BASE}/bot{bot_token}/deleteWebhook"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json={"drop_pending_updates": False})
        except httpx.TimeoutException as exc:
            raise TimeoutError("Connection timed out. Please check your token.") from exc
        except httpx.HTTPError as exc:
            raise ValueError("Не удалось связаться с Telegram API.") from exc
        data = _safe_telegram_json(response)
        if response.status_code >= 400 or not data.get("ok", True):
            raise ValueError(
                str(data.get("description") or "Не удалось отключить webhook Telegram.")
            )

    async def fetch_updates(
        self,
        bot_token: str,
        *,
        offset: int | None = None,
        timeout: int = 0,
    ) -> list[dict[str, Any]]:
        url = f"{settings.TELEGRAM_API_BASE}/bot{bot_token}/getUpdates"
        payload: dict[str, Any] = {
            "timeout": max(0, min(int(timeout), 25)),
            "allowed_updates": [
                "message",
                "edited_message",
                "callback_query",
                "business_connection",
                "business_message",
                "edited_business_message",
            ],
        }
        if offset is not None:
            payload["offset"] = int(offset)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException:
            return []
        except httpx.HTTPError as exc:
            logger.warning("TelegramService.getUpdates_http_error | error={error}", error=type(exc).__name__)
            return []
        data = _safe_telegram_json(response)
        if not data.get("ok"):
            logger.warning(
                "TelegramService.getUpdates_rejected | description={description}",
                description=str(data.get("description") or response.status_code),
            )
            return []
        result = data.get("result")
        return result if isinstance(result, list) else []

    async def register_webhook(
        self,
        bot_token: str,
        token_hash: str,
        *,
        secret_token: str | None = None,
        on_non_public: str = "polling",
    ) -> tuple[str, str]:
        """Register Telegram setWebhook, or handle non-public base URL.

        ``on_non_public``:
          - ``polling`` — deleteWebhook and fall back to getUpdates (connect/local).
          - ``skip`` — leave Telegram webhook untouched (startup bootstrap).
          - ``raise`` — raise ValueError without mutating Telegram state.
        """
        from app.core.config import is_public_https_webhook_url, resolve_webhook_base_url
        from app.core.security import generate_webhook_secret

        mode = (on_non_public or "polling").strip().lower()
        if mode not in {"polling", "skip", "raise"}:
            mode = "polling"

        webhook_url = (
            f"{resolve_webhook_base_url()}/api/v1/webhooks/telegram/{token_hash}"
        )
        secret = (secret_token or "").strip() or generate_webhook_secret()

        if not is_public_https_webhook_url(webhook_url):
            if mode == "skip":
                logger.warning(
                    "TelegramService.webhook_skip_non_public | url={url} "
                    "action=preserve_existing_telegram_webhook",
                    url=webhook_url,
                )
                return webhook_url, secret
            if mode == "raise":
                raise ValueError(
                    "WEBHOOK_BASE_URL / NGROK_TUNNEL_URL must be public HTTPS "
                    f"for setWebhook (got {webhook_url!r})."
                )
            await self.delete_webhook(bot_token)
            logger.info(
                "TelegramService.polling_mode | reason=webhook_base_not_public",
            )
            return webhook_url, secret

        url = f"{settings.TELEGRAM_API_BASE}/bot{bot_token}/setWebhook"
        payload = {
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": [
                "message",
                "edited_message",
                "callback_query",
                "business_connection",
                "business_message",
                "edited_business_message",
            ],
            "drop_pending_updates": False,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise TimeoutError("Connection timed out. Please check your token.") from exc
        except httpx.HTTPError as exc:
            raise ValueError("Не удалось связаться с Telegram API.") from exc

        data = _safe_telegram_json(response)
        if response.status_code >= 400 or not data.get("ok"):
            raise ValueError(_friendly_telegram_webhook_error(data.get("description")))

        logger.info(
            "TelegramService.webhook_registered | description={description}",
            description=data.get("description"),
        )
        return webhook_url, secret

    async def setup_telegram_bot(
        self,
        db: AsyncSession,
        payload: TelegramSetupRequest,
    ) -> TelegramSetupResponse:
        bot_token = payload.bot_token.strip()
        token_hash = hash_bot_token(bot_token)
        telegram_info = await self.verify_bot_token(bot_token)
        telegram_username = telegram_info.get("username")

        user = await self._resolve_user(db, payload.user_id)
        webhook_url, webhook_secret = await self.register_webhook(bot_token, token_hash)
        bot = await self._upsert_telegram_bot(
            db=db,
            user_id=user.id,
            bot_name=payload.bot_name,
            bot_token=bot_token,
            token_hash=token_hash,
            telegram_username=telegram_username,
            webhook_url=webhook_url,
            webhook_secret_token=webhook_secret,
        )

        return TelegramSetupResponse(
            bot_id=bot.id,
            bot_name=bot.name,
            token_hash=token_hash,
            webhook_url=webhook_url,
            telegram_username=telegram_username,
        )

    async def _client_paused_by_operator(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        external_id: str,
    ) -> bool:
        from app.models.core_models import Client

        result = await db.execute(
            select(Client).where(
                Client.bot_id == bot_id,
                Client.external_id == external_id,
            )
        )
        client = result.scalar_one_or_none()
        return bool(client and client.is_paused_by_operator)

    async def _client_on_ai_node(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        external_id: str,
    ) -> bool:
        from app.models.core_models import Client

        result = await db.execute(
            select(Client).where(
                Client.bot_id == bot_id,
                Client.external_id == external_id,
            )
        )
        client = result.scalar_one_or_none()
        if client is None or not client.current_step_id:
            return False

        flow_result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == bot_id, BotFlow.is_published.is_(True))
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        flow = flow_result.scalar_one_or_none()
        if flow is None:
            return False

        graph = flow.graph_data if isinstance(flow.graph_data, dict) else {}
        nodes = graph.get("nodes", [])
        for node in nodes:
            if node.get("id") == client.current_step_id and node.get("type") == "ai_agent":
                return True
        return False

    async def _resolve_user(self, db: AsyncSession, user_id: uuid.UUID | None) -> User:
        if user_id is not None:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise ValueError(f"User '{user_id}' not found")
            return user

        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is not None:
            return user

        user = User(
            email="demo@platform.local",
            hashed_password="!",
            company_name="Demo Workspace",
        )
        db.add(user)
        await db.flush()
        logger.info("TelegramService.demo_user_created | user_id={user_id}", user_id=user.id)
        return user

    async def _upsert_telegram_bot(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        bot_name: str,
        bot_token: str,
        token_hash: str,
        telegram_username: str | None,
        *,
        webhook_url: str | None = None,
        webhook_secret_token: str | None = None,
    ) -> Bot:
        result = await db.execute(
            select(Bot).where(
                Bot.platform_type == PlatformType.TELEGRAM,
                Bot.credentials["token_hash"].as_string() == token_hash,
            )
        )
        bot = result.scalar_one_or_none()

        credentials: dict[str, Any] = {
            "telegram_bot_token": encrypt_credential(bot_token),
            "token_hash": token_hash,
            "telegram_username": telegram_username,
        }
        if webhook_url:
            credentials["webhook_url"] = webhook_url
        if webhook_secret_token:
            credentials["webhook_secret_token"] = webhook_secret_token
            channels = {
                "telegram": {
                    "connected": True,
                    "active": True,
                    "token_hash": token_hash,
                    "telegram_username": telegram_username,
                    "webhook_url": webhook_url,
                    "webhook_secret_token": webhook_secret_token,
                    "channel": "telegram",
                }
            }
            credentials["channels"] = channels

        if bot is None:
            bot = Bot(
                user_id=user_id,
                name=bot_name,
                platform_type=PlatformType.TELEGRAM,
                is_active=True,
                credentials=credentials,
            )
            db.add(bot)
        else:
            bot.name = bot_name
            bot.is_active = True
            bot.credentials = credentials

        await db.flush()
        return bot

    def _parse_callback_query(self, callback: dict[str, Any]) -> TelegramInbound | None:
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return None

        from_user = callback.get("from") or {}
        data = str(callback.get("data") or "")

        return TelegramInbound(
            chat_id=chat_id,
            username=str(from_user.get("username") or ""),
            first_name=str(from_user.get("first_name") or ""),
            last_name=str(from_user.get("last_name") or ""),
            message_text=data,
            content_type="callback",
            callback_query_id=str(callback.get("id") or "") or None,
            raw_update={"callback_query": callback},
        )

    def _detect_media_type(self, message: dict[str, Any]) -> tuple[str, str]:
        mapping = [
            ("photo", "a photo"),
            ("sticker", "a sticker"),
            ("document", "a document"),
            ("voice", "a voice message"),
            ("video", "a video"),
            ("audio", "an audio file"),
            ("location", "a location"),
            ("contact", "a contact"),
        ]

        for key, label in mapping:
            if key in message:
                return key, f"User sent {label}."

        return "unknown", "User sent an unsupported attachment."


telegram_service = TelegramService()
