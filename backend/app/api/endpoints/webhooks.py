from __future__ import annotations

import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.users import User
from app.schemas.core_schemas import (
    WebhookQueuedResponse,
    WebhookSimulateRequest,
    WebhookSimulateResponse,
)
from app.schemas.webhook_schemas import TelegramUpdate, WhatsAppWebhookPayload
from app.services.telegram_service import telegram_service
from app.services.webhook_service import process_simulated_webhook
from app.services.whatsapp_service import whatsapp_service
from app.tasks.webhook_tasks import process_inbound_message_task

router = APIRouter(tags=["webhooks"])

_BYOK_PROVIDERS = frozenset({"telegram", "wazzup", "greenapi", "widget", "web_widget"})


@router.post(
    "/webhooks/{provider}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_200_OK,
    summary="BYOK inbound webhook — resolve tenant by payload, not URL",
)
async def provider_webhook_receiver(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    """POST /api/v1/webhooks/{telegram|wazzup|greenapi|widget} without organization_id."""
    key = (provider or "").strip().lower()
    if key not in _BYOK_PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown webhook provider.")
    if key == "wazzup":
        from app.api.endpoints.wazzup_webhook import _handle_wazzup_payload

        raw_body: Any = await request.json()
        if not isinstance(raw_body, dict):
            return Response(status_code=status.HTTP_200_OK)
        return await _handle_wazzup_payload(
            request=request,
            db=db,
            raw_body=raw_body,
            path_bot_id=None,
        )
    from app.services.webhooks.router_service import ingest_provider_webhook

    raw_bytes = await request.body()
    overlay = None
    if key == "telegram":
        overlay = request.headers.get("x-telegram-bot-id")
    return await ingest_provider_webhook(
        provider=key,
        request=request,
        db=db,
        raw_bytes=raw_bytes,
        overlay_reference_id=overlay,
    )

# Path segment → Celery worker platform_type
_CHANNEL_TYPE_ALIASES: dict[str, str] = {
    "telegram": "TELEGRAM",
    "telegram_business": "TELEGRAM",
    "whatsapp": "WHATSAPP",
    "waba": "WHATSAPP",
    "whatsapp_qr": "WHATSAPP_QR",
    "whatsapp-qr": "WHATSAPP_QR",
    "instagram": "INSTAGRAM",
    "wazzup": "WAZZUP",
    "vkontakte": "VKONTAKTE",
    "vk": "VKONTAKTE",
    "jivo": "JIVO",
    "widget": "WEB_WIDGET",
    "web_widget": "WEB_WIDGET",
    "api": "API",
    "calls": "CALLS",
    "sip": "CALLS",
}


def _normalize_channel_type(channel_type: str) -> str:
    key = (channel_type or "").strip().lower().replace(" ", "_")
    return _CHANNEL_TYPE_ALIASES.get(key, key.upper())


def _enqueue_inbound_message(
    *,
    bot_id: str,
    platform_type: str,
    payload: dict[str, Any],
    normalized: dict[str, Any] | None = None,
) -> WebhookQueuedResponse:
    """Queue Celery work on the ``inbound_messages`` stream and return immediately."""
    task_payload = dict(payload)
    if normalized is not None:
        task_payload["normalized"] = normalized
    task = process_inbound_message_task.apply_async(
        args=[bot_id, platform_type, task_payload],
        queue=settings.CELERY_INBOUND_QUEUE,
    )
    logger.info(
        "WebhookEndpoint.queued | task_id={task_id} bot_id={bot_id} platform={platform} queue={queue}",
        task_id=task.id,
        bot_id=bot_id or "resolved_in_worker",
        platform=platform_type,
        queue=settings.CELERY_INBOUND_QUEUE,
    )
    return WebhookQueuedResponse(status="queued", task_id=task.id)


def _safe_json_body(raw_body: Any) -> dict[str, Any]:
    if isinstance(raw_body, dict):
        return raw_body
    return {"raw": raw_body}


@router.post(
    "/webhook/simulate",
    response_model=WebhookQueuedResponse,
    summary="Queue a simulated inbound messenger webhook",
)
async def simulate_webhook(
    payload: WebhookSimulateRequest,
    current_user: User = Depends(get_current_user),
) -> WebhookQueuedResponse:
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook simulation is disabled in production.",
        )
    _ = current_user
    return _enqueue_inbound_message(
        bot_id=str(payload.bot_id),
        platform_type="WEBHOOK_SIMULATOR",
        payload={
            "external_id": payload.external_id,
            "username": payload.username,
            "message_text": payload.message_text,
        },
    )


@router.post(
    "/webhook/simulate/sync",
    response_model=WebhookSimulateResponse,
    summary="Synchronously simulate an inbound webhook (local debugging)",
)
async def simulate_webhook_sync(
    payload: WebhookSimulateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookSimulateResponse:
    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook simulation is disabled in production.",
        )
    _ = current_user
    try:
        return await process_simulated_webhook(
            db=db,
            bot_id=payload.bot_id,
            external_id=payload.external_id,
            username=payload.username,
            message_text=payload.message_text,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "WebhookEndpoint.simulate_sync_failed | bot_id={bot_id} external_id={external_id} error={error}",
            bot_id=payload.bot_id,
            external_id=payload.external_id,
            error=str(exc),
        )
        raise


@router.post(
    "/webhooks/telegram/{bot_token}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive Telegram Bot API updates (queued, non-blocking)",
)
async def telegram_webhook(
    bot_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    """Accept Telegram updates for the path secret registered via setWebhook.

    ``bot_token`` is the webhook path secret (token hash). Raw Telegram tokens
    that contain ``:`` are also accepted and hashed for lookup.
    """
    try:
        bot = await telegram_service.get_bot_by_token_hash(db, bot_token)
        if bot is None:
            # Also accept /webhooks/telegram/{bot_id} (UUID) used by omnichannel routing.
            try:
                from app.models.core_models import Bot as BotModel

                bot_uuid = uuid.UUID(str(bot_token))
                candidate = await db.get(BotModel, bot_uuid)
                if candidate is not None and bool(getattr(candidate, "is_active", True)):
                    bot = candidate
            except (ValueError, TypeError):
                bot = None

        if bot is None:
            logger.warning(
                "WebhookEndpoint.telegram_unknown_hash | path={path}",
                path=bot_token[:12],
            )
            return Response(status_code=status.HTTP_200_OK)

        from app.core.webhook_auth import (
            resolve_telegram_webhook_secret_for_bot,
            verify_telegram_secret_token_detailed,
        )

        expected_secret = await resolve_telegram_webhook_secret_for_bot(db, bot)
        header_secret = request.headers.get("x-telegram-bot-api-secret-token")
        secret_ok, secret_reason = verify_telegram_secret_token_detailed(
            header_secret,
            expected_secret,
        )
        if not secret_ok:
            logger.error(
                "[Telegram Webhook Error 403] reason={reason} bot_id={bot_id} "
                "path_token={path} has_header={has_header} has_stored_secret={has_stored}",
                reason=secret_reason,
                bot_id=bot.id,
                path=bot_token[:16],
                has_header=bool((header_secret or "").strip()),
                has_stored=bool((expected_secret or "").strip()),
            )
            return Response(status_code=status.HTTP_403_FORBIDDEN)

        raw_body: Any = await request.json()
        try:
            update = TelegramUpdate.model_validate(raw_body)
        except ValidationError as exc:
            logger.warning(
                "WebhookEndpoint.telegram_invalid_payload | error={error}",
                error=str(exc),
            )
            # Acknowledge to Telegram so it does not retry malformed noise forever.
            return Response(status_code=status.HTTP_200_OK)

        parsed = telegram_service.extract_inbound_fields(update)
        logger.debug(
            "WebhookEndpoint.telegram_received | bot_id={bot_id} chat_id={chat_id} text_len={length}",
            bot_id=bot.id,
            chat_id=parsed.chat_id if parsed else None,
            length=len(parsed.message_text) if parsed else 0,
        )

        from app.core.redis_client import claim_telegram_inbound

        update_id = None
        message_id = None
        if isinstance(raw_body, dict):
            if raw_body.get("update_id") is not None:
                update_id = str(raw_body.get("update_id"))
            for key in ("message", "edited_message", "business_message", "edited_business_message"):
                block = raw_body.get(key)
                if isinstance(block, dict) and block.get("message_id") is not None:
                    message_id = str(block.get("message_id"))
                    break
        if not claim_telegram_inbound(
            update_id=update_id,
            bot_id=str(bot.id),
            chat_id=parsed.chat_id if parsed else None,
            message_id=message_id,
            message_text=parsed.message_text if parsed else None,
        ):
            return Response(status_code=status.HTTP_200_OK)

        from app.services.inbound.normalizer import attach_normalized, normalize_telegram

        if parsed:
            normalized = normalize_telegram(
                bot_id=bot.id,
                chat_id=parsed.chat_id,
                message_text=parsed.message_text,
                username=parsed.username,
                first_name=parsed.first_name,
                last_name=parsed.last_name,
                raw_payload=raw_body if isinstance(raw_body, dict) else {},
            )
            payload = attach_normalized(
                {
                    "bot_id": str(bot.id),
                    "bot_token_hash": bot_token,
                    "bot_token_path": bot_token,
                    "update": update.to_raw_dict(),
                    "external_id": parsed.chat_id,
                    "username": parsed.username,
                    "first_name": parsed.first_name,
                    "last_name": parsed.last_name,
                    "message_text": parsed.message_text,
                },
                normalized,
            )
        else:
            payload = {
                "bot_id": str(bot.id),
                "bot_token_hash": bot_token,
                "bot_token_path": bot_token,
                "update": raw_body if isinstance(raw_body, dict) else {},
            }

        return _enqueue_inbound_message(
            bot_id=str(bot.id),
            platform_type="TELEGRAM",
            payload=payload,
            normalized=payload.get("normalized"),
        )
    except Exception as exc:
        logger.exception(
            "WebhookEndpoint.telegram_unhandled | error={error}",
            error=str(exc),
        )
        return Response(status_code=status.HTTP_200_OK)


@router.post(
    "/webhooks/telegram/by-hash/{bot_token_hash}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Legacy Telegram webhook path keyed by token hash",
    include_in_schema=False,
)
async def telegram_webhook_by_hash(
    bot_token_hash: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    return await telegram_webhook(bot_token=bot_token_hash, request=request, db=db)


@router.get(
    "/webhooks/whatsapp/by-hash/{token_hash}",
    summary="Legacy WhatsApp verification by credential hash",
    include_in_schema=False,
)
async def whatsapp_webhook_verify_by_hash(
    token_hash: str,
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    db: AsyncSession = Depends(get_db),
) -> int | str:
    bot = await whatsapp_service.get_bot_by_token_hash(db, token_hash)
    if bot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found.")
    return await whatsapp_webhook_verify(
        bot_id=bot.id,
        hub_mode=hub_mode,
        hub_verify_token=hub_verify_token,
        hub_challenge=hub_challenge,
        db=db,
    )


@router.post(
    "/webhooks/whatsapp/by-hash/{token_hash}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Legacy WhatsApp webhook path keyed by credential hash",
    include_in_schema=False,
)
async def whatsapp_webhook_by_hash(
    token_hash: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    bot = await whatsapp_service.get_bot_by_token_hash(db, token_hash)
    if bot is None:
        logger.warning(
            "WebhookEndpoint.whatsapp_unknown_hash | token_hash={hash}",
            hash=token_hash[:12],
        )
        return Response(status_code=status.HTTP_200_OK)
    return await whatsapp_webhook(bot_id=bot.id, request=request)


@router.get(
    "/webhooks/whatsapp/{bot_id}",
    summary="Meta WhatsApp webhook verification challenge",
)
async def whatsapp_webhook_verify(
    bot_id: uuid.UUID,
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    db: AsyncSession = Depends(get_db),
) -> int | str:
    logger.info(
        "WebhookEndpoint.whatsapp_verify | bot_id={bot_id} mode={mode}",
        bot_id=bot_id,
        mode=hub_mode,
    )
    if hub_mode != "subscribe" or not hub_challenge:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WhatsApp webhook verification failed.",
        )

    bot = await whatsapp_service.get_bot_by_id(db, bot_id)
    if bot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found.")

    expected = whatsapp_service.get_verify_token(bot)
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WhatsApp verify token is not configured for this bot.",
        )
    if not secrets.compare_digest(str(hub_verify_token), str(expected)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WhatsApp verify token mismatch.",
        )

    try:
        return int(hub_challenge)
    except ValueError:
        return hub_challenge


@router.post(
    "/webhooks/whatsapp/{bot_id}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive WhatsApp Cloud API webhook events (queued, non-blocking)",
)
async def whatsapp_webhook(
    bot_id: uuid.UUID,
    request: Request,
) -> WebhookQueuedResponse | Response:
    try:
        raw_bytes = await request.body()
        from app.core.webhook_auth import require_meta_signature

        try:
            require_meta_signature(request, raw_bytes)
        except HTTPException:
            logger.warning(
                "WebhookEndpoint.whatsapp_bad_signature | bot_id={bot_id}",
                bot_id=bot_id,
            )
            return Response(status_code=status.HTTP_403_FORBIDDEN)

        import json as _json

        try:
            raw_body: Any = _json.loads(raw_bytes.decode("utf-8") or "{}")
        except Exception:
            return Response(status_code=status.HTTP_200_OK)

        try:
            body = WhatsAppWebhookPayload.model_validate(raw_body)
        except ValidationError as exc:
            logger.warning(
                "WebhookEndpoint.whatsapp_invalid_payload | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
            return Response(status_code=status.HTTP_200_OK)

        inbound_preview = whatsapp_service.extract_typed_inbound_messages(body)
        first = inbound_preview[0] if inbound_preview else None
        logger.debug(
            "WebhookEndpoint.whatsapp_received | bot_id={bot_id} messages={count}",
            bot_id=bot_id,
            count=len(inbound_preview),
        )

        # Redis idempotency — skip duplicate Cloud API deliveries (24h TTL).
        from app.core.redis_client import (
            claim_whatsapp_message_id,
            extract_cloud_whatsapp_message_ids,
        )

        message_ids = extract_cloud_whatsapp_message_ids(body.to_raw_dict())
        if message_ids:
            claimed = [mid for mid in message_ids if claim_whatsapp_message_id(mid)]
            if not claimed:
                logger.info(
                    "WebhookEndpoint.whatsapp_dedup_skip | bot_id={bot_id} ids={ids}",
                    bot_id=bot_id,
                    ids=len(message_ids),
                )
                return Response(status_code=status.HTTP_200_OK)

        from app.services.inbound.normalizer import attach_normalized, normalize_whatsapp

        base_payload: dict[str, Any] = {
            "bot_id": str(bot_id),
            "body": body.to_raw_dict(),
            "external_id": first.external_id if first else None,
            "username": first.username if first else None,
            "first_name": first.first_name if first else None,
            "last_name": first.last_name if first else None,
            "message_text": first.message_text if first else None,
        }
        if first:
            normalized = normalize_whatsapp(
                bot_id=bot_id,
                phone=first.external_id,
                message_text=first.message_text,
                client_name=first.first_name or first.username,
                provider="whatsapp",
                raw_payload=body.to_raw_dict(),
            )
            payload = attach_normalized(base_payload, normalized)
        else:
            payload = base_payload

        return _enqueue_inbound_message(
            bot_id=str(bot_id),
            platform_type="WHATSAPP",
            payload=payload,
            normalized=payload.get("normalized"),
        )
    except Exception as exc:
        logger.exception(
            "WebhookEndpoint.whatsapp_unhandled | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        return Response(status_code=status.HTTP_200_OK)


@router.post(
    "/webhooks/whatsapp-qr",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive inbound WhatsApp QR (Baileys) messages from the Node microservice",
)
async def whatsapp_qr_webhook(
    request: Request,
) -> WebhookQueuedResponse | dict[str, Any]:
    from app.core.webhook_auth import require_internal_service_key
    from app.services.inbound.normalizer import attach_normalized, normalize_whatsapp_qr

    try:
        require_internal_service_key(request)
    except HTTPException:
        return {"status": "forbidden", "reason": "auth_required"}

    raw_body: Any = await request.json()
    if not isinstance(raw_body, dict):
        return {"status": "ignored", "reason": "invalid_json"}

    bot_id = str(raw_body.get("bot_id") or "").strip()
    from_phone = str(raw_body.get("from") or "").strip()
    message_text = str(raw_body.get("message_text") or "").strip()
    if not bot_id:
        logger.warning("WebhookEndpoint.whatsapp_qr_missing_bot_id")
        return {"status": "ignored", "reason": "missing_bot_id"}
    if not from_phone or not message_text:
        return {"status": "ignored", "reason": "incomplete_payload"}

    # Redis idempotency — Baileys may retry; skip duplicate message_id (24h TTL).
    from app.core.redis_client import claim_whatsapp_message_id

    message_id = raw_body.get("message_id")
    if message_id and not claim_whatsapp_message_id(str(message_id)):
        logger.info(
            "WebhookEndpoint.whatsapp_qr_dedup_skip | bot_id={bot_id} message_id={message_id}",
            bot_id=bot_id,
            message_id=str(message_id)[:64],
        )
        return {"status": "duplicate", "skipped": True}

    try:
        bot_uuid = uuid.UUID(bot_id)
    except ValueError:
        return {"status": "ignored", "reason": "invalid_bot_id"}

    normalized = normalize_whatsapp_qr(
        bot_id=bot_uuid,
        from_phone=from_phone,
        message_text=message_text,
        push_name=str(raw_body.get("push_name") or from_phone),
        raw_payload=raw_body,
    )
    payload = attach_normalized(
        {
            "bot_id": bot_id,
            "body": raw_body,
            "external_id": from_phone,
            "username": from_phone,
            "first_name": str(raw_body.get("push_name") or from_phone),
            "message_text": message_text,
        },
        normalized,
    )
    return _enqueue_inbound_message(
        bot_id=bot_id,
        platform_type="WHATSAPP_QR",
        payload=payload,
        normalized=payload.get("normalized"),
    )


@router.get(
    "/webhooks/instagram/{bot_id}",
    summary="Meta Instagram webhook verification challenge",
)
async def instagram_webhook_verify(
    bot_id: uuid.UUID,
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    db: AsyncSession = Depends(get_db),
) -> int | str:
    if hub_mode != "subscribe" or not hub_challenge:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IG verify failed")

    from sqlalchemy import select

    from app.models.channels import BotChannel, HubChannelStatus, HubChannelType

    result = await db.execute(
        select(BotChannel).where(
            BotChannel.bot_id == bot_id,
            BotChannel.channel_type == HubChannelType.INSTAGRAM,
            BotChannel.status == HubChannelStatus.CONNECTED,
        )
    )
    channel = result.scalar_one_or_none()
    expected = str((channel.meta_data or {}).get("verify_token") or "") if channel else ""
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IG verify token is not configured for this bot.",
        )
    if not secrets.compare_digest(str(hub_verify_token), str(expected)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IG verify token mismatch")

    try:
        return int(hub_challenge)
    except ValueError:
        return hub_challenge


@router.post(
    "/webhooks/instagram/{bot_id}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive Instagram Direct messaging webhooks",
)
async def instagram_webhook(
    bot_id: uuid.UUID,
    request: Request,
) -> WebhookQueuedResponse | Response:
    try:
        raw_bytes = await request.body()
        from app.core.webhook_auth import require_meta_signature

        try:
            require_meta_signature(request, raw_bytes)
        except HTTPException:
            logger.warning(
                "WebhookEndpoint.instagram_bad_signature | bot_id={bot_id}",
                bot_id=bot_id,
            )
            return Response(status_code=status.HTTP_403_FORBIDDEN)

        import json as _json

        try:
            raw_body: Any = _json.loads(raw_bytes.decode("utf-8") or "{}")
        except Exception:
            return Response(status_code=status.HTTP_200_OK)
        if not isinstance(raw_body, dict):
            return Response(status_code=status.HTTP_200_OK)

        from app.core.redis_client import claim_inbound_event

        # Prefer Meta messaging mid when present.
        event_id = None
        try:
            entry0 = (raw_body.get("entry") or [None])[0] or {}
            messaging0 = (entry0.get("messaging") or [None])[0] or {}
            event_id = str(messaging0.get("message", {}).get("mid") or messaging0.get("mid") or "") or None
        except Exception:
            event_id = None
        if event_id and not claim_inbound_event("instagram", event_id):
            return Response(status_code=status.HTTP_200_OK)

        return _enqueue_inbound_message(
            bot_id=str(bot_id),
            platform_type="INSTAGRAM",
            payload={"bot_id": str(bot_id), "body": raw_body},
        )
    except Exception as exc:
        logger.exception(
            "WebhookEndpoint.instagram_unhandled | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        return Response(status_code=status.HTTP_200_OK)


@router.post(
    "/webhooks/jivo/{bot_id}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive Jivo Chat API inbound events",
)
async def jivo_webhook(
    bot_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    from app.models.core_models import Bot as BotModel
    from app.services.bot_app_integrations_service import bot_app_integrations_service

    bot = await db.get(BotModel, bot_id)
    if bot is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    cfg = bot_app_integrations_service._read_integration(bot, "jivo")
    if not cfg.get("connected"):
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    raw_body: Any = await request.json()
    if not isinstance(raw_body, dict):
        return Response(status_code=status.HTTP_200_OK)

    sender = raw_body.get("sender") if isinstance(raw_body.get("sender"), dict) else {}
    message = raw_body.get("message") if isinstance(raw_body.get("message"), dict) else {}
    external_id = str(
        raw_body.get("chat_id") or sender.get("id") or raw_body.get("client_id") or ""
    )
    text = str(message.get("text") or raw_body.get("text") or "")
    return _enqueue_inbound_message(
        bot_id=str(bot_id),
        platform_type="JIVO",
        payload={
            "bot_id": str(bot_id),
            "body": raw_body,
            "external_id": external_id or None,
            "username": str(sender.get("name") or ""),
            "message_text": text or None,
        },
    )


@router.post(
    "/webhooks/widget/{bot_id}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive site-chat widget messages",
)
async def widget_webhook(
    bot_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | dict[str, Any]:
    from sqlalchemy import select

    from app.models.channels import BotChannel, HubChannelStatus, HubChannelType

    raw_body: Any = await request.json()
    if not isinstance(raw_body, dict):
        return {"status": "ignored", "reason": "invalid_json"}

    result = await db.execute(
        select(BotChannel).where(
            BotChannel.bot_id == bot_id,
            BotChannel.channel_type == HubChannelType.WEB_WIDGET,
            BotChannel.status == HubChannelStatus.CONNECTED,
        )
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    expected = str((channel.meta_data or {}).get("widget_token") or "")
    provided = (
        request.headers.get("x-widget-token")
        or str(raw_body.get("widget_token") or "")
    ).strip()
    if expected and provided and not secrets.compare_digest(expected, provided):
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    external_id = str(raw_body.get("session_id") or raw_body.get("external_id") or "").strip()
    if not external_id:
        external_id = f"web-{uuid.uuid4().hex[:12]}"
    text = str(raw_body.get("message_text") or raw_body.get("text") or "").strip()
    from app.services.inbound.normalizer import attach_normalized, normalize_web_widget

    normalized = normalize_web_widget(
        bot_id=bot_id,
        session_id=external_id,
        message_text=text,
        username=str(raw_body.get("username") or "web-visitor"),
        raw_payload=raw_body,
    )
    payload = attach_normalized(
        {
            "bot_id": str(bot_id),
            "body": raw_body,
            "external_id": external_id,
            "username": str(raw_body.get("username") or "web-visitor"),
            "message_text": text or None,
        },
        normalized,
    )
    queued = _enqueue_inbound_message(
        bot_id=str(bot_id),
        platform_type="WEB_WIDGET",
        payload=payload,
        normalized=payload.get("normalized"),
    )
    return {
        "status": "queued",
        "task_id": queued.task_id,
        "session_id": external_id,
    }


@router.post(
    "/webhooks/api/{bot_id}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generic HTTP API inbound channel",
)
async def api_channel_webhook(
    bot_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    from sqlalchemy import select

    from app.core.security import decrypt_credential
    from app.models.channels import BotChannel, HubChannelStatus, HubChannelType

    result = await db.execute(
        select(BotChannel).where(
            BotChannel.bot_id == bot_id,
            BotChannel.channel_type == HubChannelType.API,
            BotChannel.status == HubChannelStatus.CONNECTED,
        )
    )
    channel = result.scalar_one_or_none()
    if channel is None or not channel.encrypted_token:
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    try:
        expected = decrypt_credential(channel.encrypted_token)
    except Exception:
        expected = channel.encrypted_token
    provided = (
        request.headers.get("x-api-key")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    if not provided or not secrets.compare_digest(str(expected), str(provided)):
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    raw_body: Any = await request.json()
    if not isinstance(raw_body, dict):
        return Response(status_code=status.HTTP_200_OK)
    return _enqueue_inbound_message(
        bot_id=str(bot_id),
        platform_type="API",
        payload={
            "bot_id": str(bot_id),
            "body": raw_body,
            "external_id": str(raw_body.get("external_id") or raw_body.get("user_id") or "")
            or None,
            "username": str(raw_body.get("username") or ""),
            "message_text": str(raw_body.get("message_text") or raw_body.get("text") or "")
            or None,
        },
    )


@router.post(
    "/webhooks/calls/{bot_id}",
    response_model=WebhookQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="SIP / telephony inbound events (transcript or DTMF → text)",
)
async def calls_webhook(
    bot_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookQueuedResponse | Response:
    from sqlalchemy import select

    from app.models.channels import BotChannel, HubChannelStatus, HubChannelType

    result = await db.execute(
        select(BotChannel).where(
            BotChannel.bot_id == bot_id,
            BotChannel.channel_type == HubChannelType.CALLS,
            BotChannel.status == HubChannelStatus.CONNECTED,
        )
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    raw_body: Any = await request.json()
    if not isinstance(raw_body, dict):
        return Response(status_code=status.HTTP_200_OK)
    text = str(
        raw_body.get("transcript")
        or raw_body.get("message_text")
        or raw_body.get("text")
        or raw_body.get("dtmf")
        or ""
    )
    return _enqueue_inbound_message(
        bot_id=str(bot_id),
        platform_type="CALLS",
        payload={
            "bot_id": str(bot_id),
            "body": raw_body,
            "external_id": str(raw_body.get("call_id") or raw_body.get("from") or "") or None,
            "username": str(raw_body.get("caller_name") or raw_body.get("from") or ""),
            "message_text": text or None,
        },
    )


@router.get(
    "/webhooks/widget/{bot_id}/poll/{session_id}",
    summary="Poll AI replies for the site-chat widget",
)
async def widget_poll_replies(
    bot_id: uuid.UUID,
    session_id: str,
) -> dict[str, Any]:
    from app.core.redis_client import get_redis_client

    try:
        client = get_redis_client()
        key = f"widget:reply:{bot_id}:{session_id}"
        messages: list[str] = []
        while True:
            item = client.rpop(key)
            if item is None:
                break
            messages.append(str(item))
        return {"session_id": session_id, "messages": messages}
    except Exception as exc:
        logger.warning(
            "WebhookEndpoint.widget_poll_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        return {"session_id": session_id, "messages": []}


@router.post(
    "/webhooks/payments",
    summary="Unified payment gateway webhook (Stripe payment_intent / checkout)",
    include_in_schema=True,
)
async def unified_payments_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | bool]:
    """
    Accepts Stripe ``checkout.session.completed`` and ``payment_intent.succeeded``.
    Registered before ``/webhooks/payments/{provider}`` to avoid path conflicts.
    """
    from app.services.billing.payment_billing_service import payment_billing_service

    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        return await payment_billing_service.handle_payments_webhook(
            db,
            raw_body=raw,
            headers=headers,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Payment.webhook_error | error={error}", error=str(exc))
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment webhook processing failed.",
        ) from exc


@router.post(
    "/webhooks/payments/{provider}",
    summary="Payment provider webhook (Stripe / TipTop Pay / manual)",
    include_in_schema=True,
)
async def payment_provider_webhook(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | bool | float | None]:
    """
    TipTop Pay: ``POST /api/v1/webhooks/payments/tiptop`` with ``Content-HMAC`` header.

    Handles CloudPayments Pay notifications — verifies HMAC, reads ``Data.organization_id``
    and ``Amount``, credits org wallet via pending ``PaymentInvoice``.
    """
    from app.services.billing.payment_billing_service import payment_billing_service
    from app.services.billing_service import process_successful_payment

    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    provider_norm = (provider or "").strip().lower()

    if provider_norm in {"tiptop", "freedom"}:
        try:
            return await payment_billing_service.handle_tiptop_webhook(
                db,
                raw_body=raw,
                headers=headers,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if provider_norm == "stripe":
        try:
            return await payment_billing_service.handle_payments_webhook(
                db,
                raw_body=raw,
                headers=headers,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if not payment_billing_service.verify_provider_signature(
        provider_norm,
        raw_body=raw,
        headers=headers,
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid payment signature.")

    external_id: str | None = None

    if provider_norm == "stripe":
        parsed = await payment_billing_service.parse_stripe_checkout_external_id(raw, headers)
        if parsed is None:
            return {"status": "ignored"}
        _, external_id = parsed
    else:
        try:
            import json as _json

            payload = _json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        external_id = str(
            payload.get("external_payment_id")
            or payload.get("payment_id")
            or "",
        ).strip()
        if not external_id and isinstance(payload.get("object"), dict):
            external_id = str(payload["object"].get("id") or "").strip()

    if not external_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing payment identifier.")

    ok = await process_successful_payment(
        db,
        external_payment_id=external_id,
        provider=provider_norm,
        provider_signature_data={"headers": headers},
    )
    return {"status": "ok", "processed": ok}


@router.post(
    "/webhooks/bitrix24/{connection_id}",
    status_code=status.HTTP_200_OK,
    summary="Bitrix24 mass-market event handler (application_token verify → queue)",
)
async def bitrix24_connection_webhook(
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.services.integration_hub.bitrix_webhook import ingest_bitrix24_webhook

    return await ingest_bitrix24_webhook(connection_id=connection_id, request=request, db=db)


@router.post(
    "/webhooks/amocrm/{connection_id}",
    status_code=status.HTTP_200_OK,
    summary="amoCRM event handler (account match → queue)",
)
async def amocrm_connection_webhook(
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.services.integration_hub.amocrm_webhook import ingest_amocrm_webhook

    return await ingest_amocrm_webhook(connection_id=connection_id, request=request, db=db)


@router.post(
    "/webhooks/wazzup/{connection_id}",
    status_code=status.HTTP_200_OK,
    summary="Wazzup MessagingAdapter webhook (message.received → queue)",
)
async def wazzup_connection_webhook(
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    try:
        raw_body: Any = await request.json()
    except Exception:
        raw_body = {}
    if not isinstance(raw_body, dict):
        return Response(status_code=status.HTTP_200_OK)
    if raw_body.get("test") is True:
        return Response(status_code=status.HTTP_200_OK)
    from app.models.integration_hub import IntegrationConnection
    from app.services.integration_hub.wazzup_webhook import ingest_wazzup_hub_webhook

    connection = await db.get(IntegrationConnection, connection_id)
    if connection is not None and connection.provider == "wazzup":
        return await ingest_wazzup_hub_webhook(
            connection_id=connection_id, payload=raw_body, db=db
        )
    from app.api.endpoints.wazzup_webhook import _handle_wazzup_payload

    return await _handle_wazzup_payload(
        request=request,
        db=db,
        raw_body=raw_body,
        path_bot_id=connection_id,
    )


@router.post(
    "/webhooks/kaspi_pay/{connection_id}",
    status_code=status.HTTP_200_OK,
    summary="Kaspi Pay invoice status webhook (verify → queue)",
)
async def kaspi_pay_connection_webhook(
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.services.integration_hub.kaspi_webhook import ingest_kaspi_pay_webhook

    return await ingest_kaspi_pay_webhook(connection_id=connection_id, request=request, db=db)


@router.post(
    "/webhooks/{channel_type}/{bot_id}",
    status_code=status.HTTP_200_OK,
    response_model=None,
    summary="Universal Dynamic Webhook Receiver — always ACK 200, enqueue inbound_messages",
)
async def universal_webhook_receiver(
    channel_type: str,
    bot_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Authenticate then enqueue. Channel-specific routes take priority when matched."""
    platform = _normalize_channel_type(channel_type)
    bot_id_str = str(bot_id)
    task_id: str | None = None
    raw_bytes = await request.body()

    try:
        if platform in {"WHATSAPP", "INSTAGRAM"}:
            from app.core.webhook_auth import require_meta_signature

            require_meta_signature(request, raw_bytes)
        elif platform == "TELEGRAM":
            from app.core.webhook_auth import (
                resolve_telegram_webhook_secret_for_bot,
                verify_telegram_secret_token_detailed,
            )
            from app.models.core_models import Bot as BotModel

            bot_row = await db.get(BotModel, bot_id)
            expected = (
                await resolve_telegram_webhook_secret_for_bot(db, bot_row)
                if bot_row is not None
                else None
            )
            header_secret = request.headers.get("x-telegram-bot-api-secret-token")
            secret_ok, secret_reason = verify_telegram_secret_token_detailed(
                header_secret,
                expected,
            )
            if not secret_ok:
                logger.error(
                    "[Telegram Webhook Error 403] reason={reason} bot_id={bot_id} "
                    "has_header={has_header} has_stored_secret={has_stored}",
                    reason=secret_reason,
                    bot_id=bot_id_str,
                    has_header=bool((header_secret or "").strip()),
                    has_stored=bool((expected or "").strip()),
                )
                return Response(status_code=status.HTTP_403_FORBIDDEN)
        else:
            from app.core.webhook_auth import require_internal_service_key

            require_internal_service_key(request)
    except HTTPException as auth_exc:
        # Fail closed with real HTTP status (not a soft 200 JSON body).
        code = int(getattr(auth_exc, "status_code", 403) or 403)
        if code < 400:
            code = 403
        return Response(status_code=code)

    try:
        import json as _json

        try:
            raw_body: Any = _json.loads(raw_bytes.decode("utf-8") or "{}")
        except Exception as parse_exc:
            logger.warning(
                "WebhookReceiver.body_parse_failed | channel={channel} bot_id={bot_id} error={error}",
                channel=platform,
                bot_id=bot_id_str,
                error=str(parse_exc),
            )
            raw_body = {}

        body = _safe_json_body(raw_body)
        headers_meta = {
            "content_type": request.headers.get("content-type"),
            "user_agent": request.headers.get("user-agent"),
            "x_hub_signature_present": bool(
                request.headers.get("x-hub-signature-256")
                or request.headers.get("x-hub-signature")
            ),
        }

        payload: dict[str, Any] = {
            "bot_id": bot_id_str,
            "channel_type": channel_type,
            "platform_type": platform,
            "body": body,
            "headers": headers_meta,
            "received_path": f"/api/v1/webhooks/{channel_type}/{bot_id_str}",
        }

        if platform == "TELEGRAM":
            try:
                update = TelegramUpdate.model_validate(body)
                parsed = telegram_service.extract_inbound_fields(update)
                payload["update"] = update.to_raw_dict() if parsed else body
                if parsed:
                    payload["external_id"] = parsed.chat_id
                    payload["username"] = parsed.username
                    payload["first_name"] = parsed.first_name
                    payload["last_name"] = parsed.last_name
                    payload["message_text"] = parsed.message_text
            except ValidationError as exc:
                logger.warning(
                    "WebhookReceiver.telegram_soft_validate | bot_id={bot_id} error={error}",
                    bot_id=bot_id_str,
                    error=str(exc),
                )
                payload["update"] = body

        elif platform == "WHATSAPP":
            try:
                wa = WhatsAppWebhookPayload.model_validate(body)
                inbound_preview = whatsapp_service.extract_typed_inbound_messages(wa)
                first = inbound_preview[0] if inbound_preview else None
                payload["body"] = wa.to_raw_dict()
                if first:
                    payload["external_id"] = first.external_id
                    payload["username"] = first.username
                    payload["first_name"] = first.first_name
                    payload["last_name"] = first.last_name
                    payload["message_text"] = first.message_text
            except ValidationError as exc:
                logger.warning(
                    "WebhookReceiver.whatsapp_soft_validate | bot_id={bot_id} error={error}",
                    bot_id=bot_id_str,
                    error=str(exc),
                )

        elif platform == "WHATSAPP_QR":
            payload["external_id"] = str(
                body.get("external_id") or body.get("chat_id") or body.get("from") or ""
            ) or None
            payload["message_text"] = (
                body.get("message_text") or body.get("text") or body.get("body")
            )
            payload["username"] = body.get("username") or body.get("push_name")

        logger.info(
            "WebhookReceiver.accepted | channel={channel} bot_id={bot_id} keys={keys}",
            channel=platform,
            bot_id=bot_id_str,
            keys=sorted(body.keys())[:20] if isinstance(body, dict) else [],
        )

        try:
            queued = _enqueue_inbound_message(
                bot_id=bot_id_str,
                platform_type=platform,
                payload=payload,
            )
            task_id = queued.task_id
        except Exception as enqueue_exc:
            logger.exception(
                "WebhookReceiver.enqueue_failed | channel={channel} bot_id={bot_id} error={error}",
                channel=platform,
                bot_id=bot_id_str,
                error=str(enqueue_exc),
            )
            return {
                "status": "ok",
                "queued": False,
                "channel_type": channel_type,
                "bot_id": bot_id_str,
                "error": "enqueue_failed",
            }

        return {
            "status": "ok",
            "queued": True,
            "task_id": task_id,
            "channel_type": channel_type,
            "platform_type": platform,
            "bot_id": bot_id_str,
            "queue": settings.CELERY_INBOUND_QUEUE,
        }

    except Exception as exc:
        logger.exception(
            "WebhookReceiver.unhandled | channel={channel} bot_id={bot_id} error={error}",
            channel=channel_type,
            bot_id=bot_id_str,
            error=str(exc),
        )
        return {
            "status": "ok",
            "queued": False,
            "channel_type": channel_type,
            "bot_id": bot_id_str,
            "error": "receiver_exception",
        }


wazzup_public_router = APIRouter(tags=["webhooks"])


@wazzup_public_router.post(
    "/webhooks/wazzup/{connection_id}",
    status_code=status.HTTP_200_OK,
    summary="Wazzup public webhook alias (no /api/v1 prefix)",
)
async def wazzup_public_connection_webhook(
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await wazzup_connection_webhook(connection_id, request, db)


@wazzup_public_router.post(
    "/webhooks/kaspi_pay/{connection_id}",
    status_code=status.HTTP_200_OK,
    summary="Kaspi Pay public webhook alias (no /api/v1 prefix)",
)
async def kaspi_pay_public_connection_webhook(
    connection_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await kaspi_pay_connection_webhook(connection_id, request, db)

