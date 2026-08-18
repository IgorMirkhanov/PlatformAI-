"""
Production messenger webhook consumer.

Celery tasks in ``app.tasks.webhook_tasks`` invoke this module so inbound
Telegram / WhatsApp payloads run through:

1. Bot + published ``compiled_graph`` resolution (Postgres → in-memory cache)
2. Operator pause gate (``is_paused_by_operator`` → history only, no automation)
3. ``FlowExecutor(compiled_graph)`` sequential node walk (LLM / Condition / CRM)
4. Channel outbound dispatch:
   - Telegram ``sendMessage`` / ``sendPhoto`` / ``sendDocument``
   - WhatsApp Cloud API text + media links
   - WhatsApp QR (Baileys) text + ``/api/send-media``
5. Broken media URLs fall back to text-only and are logged to ``BotDiagnosticLogs``
6. ``chat_history`` persistence for the Live Operator Inbox
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.flow_cache import published_flow_cache
from app.models.core_models import Bot, BotFlow
from app.schemas.media_schemas import MediaAttachment
from app.services.flow_parser import FlowExecutor
from app.services.instagram_service import instagram_service
from app.services.media_dispatch_service import deliver_attachments_safely
from app.services.messenger_errors import MessengerAPIError
from app.services.telegram_service import telegram_service
from app.services.wazzup_service import wazzup_service
from app.services.webhook_service import process_inbound_message
from app.services.whatsapp_qr_service import whatsapp_qr_service
from app.services.whatsapp_service import whatsapp_service


async def load_compiled_graph(db: AsyncSession, bot_id: uuid.UUID) -> dict[str, Any]:
    """Resolve the published compiled graph for a bot (cache → Postgres)."""
    cached = published_flow_cache.get(bot_id)
    if cached and isinstance(cached.graph_data, dict) and cached.graph_data.get("nodes"):
        return dict(cached.graph_data)

    result = await db.execute(
        select(BotFlow)
        .where(BotFlow.bot_id == bot_id, BotFlow.is_published.is_(True))
        .order_by(BotFlow.updated_at.desc())
        .limit(1)
    )
    flow = result.scalar_one_or_none()
    if flow is None:
        result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == bot_id)
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        flow = result.scalar_one_or_none()

    graph = flow.graph_data if flow and isinstance(flow.graph_data, dict) else {}
    if flow and graph:
        published_flow_cache.put_from_orm(
            flow_id=flow.id,
            bot_id=bot_id,
            title=flow.title,
            graph_data=graph,
            is_published=bool(flow.is_published),
            updated_at=flow.updated_at,
        )
    return dict(graph or {})


async def execute_flow_for_inbound(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    external_id: str,
    username: str,
    first_name: str,
    message_text: str,
    source: str = "webhook",
    inbound_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Instantiate ``FlowExecutor(compiled_graph)`` and run nodes until a reply is ready.

    Channel adapters normally go through ``process_inbound_message`` (which uses the
    same executor). This helper is the explicit Celery-worker entry for sequential
    graph execution + shared persistence/outbound packaging.
    """
    bot = await db.get(Bot, bot_id)
    if bot is None:
        return {"status": "ignored", "reason": "bot_not_found"}

    compiled_graph = await load_compiled_graph(db, bot_id)
    preview = FlowExecutor(compiled_graph)
    logger.info(
        "WebhookWorker.flow_executor_ready | bot_id={bot_id} nodes={nodes} edges={edges}",
        bot_id=bot_id,
        nodes=len(preview.nodes),
        edges=len(preview.edges),
    )

    # Shared orchestration instantiates FlowExecutor(compiled_graph) and walks
    # LLM / Condition / CRM nodes until a messenger reply is ready.
    flow_result = await process_inbound_message(
        db=db,
        bot_id=bot_id,
        external_id=external_id,
        username=username,
        first_name=first_name,
        message_text=message_text,
        source=source,
        inbound_payload=inbound_payload,
    )
    return {
        "status": "processed",
        "client_id": str(flow_result.client_id),
        "response_text": flow_result.response_text,
        "bot_silent": flow_result.bot_silent,
        "current_step_id": flow_result.current_step_id,
        "media_attachments": [
            item.model_dump() for item in (flow_result.media_attachments or [])
        ],
    }


async def process_inbound_message_worker(
    bot_id: str,
    platform_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Background worker entry: resolve channel, run FlowExecutor pipeline, dispatch reply.

    Returns a structured status dict. Non-retriable messenger API failures
    (revoked token, hard 403) are caught and returned without raising so Celery
    does not spin useless retries. Media attachment failures never fail the task.
    """
    platform = platform_type.upper()

    async with async_session_factory() as db:
        try:
            result = await _dispatch_platform(db, bot_id=bot_id, platform=platform, payload=payload)
            await db.commit()
            return result
        except MessengerAPIError as exc:
            await db.rollback()
            logger.error(
                "WebhookWorker.messenger_api_error | bot_id={bot_id} platform={platform} "
                "status={status} retriable={retriable} detail={detail}",
                bot_id=bot_id or "unresolved",
                platform=platform,
                status=exc.status_code,
                retriable=exc.retriable,
                detail=exc.detail[:500],
            )
            if exc.retriable:
                raise
            return {
                "status": "failed",
                "reason": "messenger_api_error",
                "channel": exc.channel,
                "status_code": exc.status_code,
                "detail": exc.detail[:500],
            }
        except Exception:
            await db.rollback()
            raise


async def dispatch_result_media_attachments(
    *,
    platform: str,
    attachments: list[MediaAttachment] | list[Any],
    send_fn: Any,
    bot_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    db: AsyncSession | None,
) -> int:
    """
    Shared worker helper: deliver attachments with probe + diagnostic fallback.

    Channel services already call their own dispatchers; this helper is available
    for generic/simulator paths and future adapters.
    """
    if not attachments:
        return 0

    normalized: list[MediaAttachment] = []
    for item in attachments:
        if isinstance(item, MediaAttachment):
            normalized.append(item)
        else:
            try:
                normalized.append(MediaAttachment.model_validate(item))
            except Exception:
                continue

    delivered = await deliver_attachments_safely(
        normalized,
        send_fn=send_fn,
        bot_id=bot_id,
        client_id=client_id,
        db=db,
    )
    logger.info(
        "WebhookWorker.media_dispatched | platform={platform} delivered={delivered}/{total}",
        platform=platform,
        delivered=len(delivered),
        total=len(normalized),
    )
    return len(delivered)


async def _dispatch_platform(
    db: AsyncSession,
    *,
    bot_id: str,
    platform: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if platform == "TELEGRAM":
        token_hash = str(
            payload.get("bot_token_hash") or payload.get("bot_token_path") or ""
        ).strip()
        update = payload.get("update") or payload.get("body") or {}

        # Universal route supplies bot_id — resolve token_hash from stored credentials.
        if not token_hash and bot_id:
            try:
                bot_uuid = uuid.UUID(str(bot_id))
            except ValueError:
                bot_uuid = None
            if bot_uuid is not None:
                from app.models.core_models import Bot

                bot = await db.get(Bot, bot_uuid)
                credentials = bot.credentials if bot and isinstance(bot.credentials, dict) else {}
                token_hash = str(credentials.get("token_hash") or "").strip()
                channels = (
                    credentials.get("channels")
                    if isinstance(credentials.get("channels"), dict)
                    else {}
                )
                telegram_channel = (
                    channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
                )
                if not token_hash:
                    token_hash = str(telegram_channel.get("token_hash") or "").strip()

        if not token_hash:
            logger.warning(
                "WebhookWorker.telegram_missing_hash | bot_id={bot_id}",
                bot_id=bot_id or "unresolved",
            )
            return {"status": "ignored", "reason": "missing_token_hash"}

        if not isinstance(update, dict):
            update = {}

        return await telegram_service.process_queued_webhook(
            db=db,
            bot_token_hash=token_hash,
            update=update,
        )

    if platform == "WHATSAPP":
        resolved_bot_id = payload.get("bot_id") or bot_id
        whatsapp_bot_uuid: uuid.UUID | None = None
        if resolved_bot_id:
            try:
                whatsapp_bot_uuid = uuid.UUID(str(resolved_bot_id))
            except ValueError:
                whatsapp_bot_uuid = None
        return await whatsapp_service.process_queued_webhook(
            db=db,
            bot_id=whatsapp_bot_uuid,
            token_hash=str(payload["token_hash"]) if payload.get("token_hash") else None,
            webhook_body=payload["body"],
        )

    if platform in {"WHATSAPP_QR", "WHATSAPP-QR"}:
        return await whatsapp_qr_service.process_inbound_webhook(db, payload)

    if platform == "INSTAGRAM":
        return await instagram_service.process_queued_webhook(
            db=db,
            bot_id=uuid.UUID(str(payload.get("bot_id") or bot_id)),
            webhook_body=payload.get("body") or {},
        )

    if platform == "WAZZUP":
        return await wazzup_service.process_queued_webhook(
            db=db,
            bot_id=uuid.UUID(str(payload.get("bot_id") or bot_id)),
            webhook_body=payload.get("body") or {},
        )

    if platform in {"WEBHOOK_SIMULATOR", "SIMULATOR"}:
        return await execute_flow_for_inbound(
            db,
            bot_id=uuid.UUID(bot_id),
            external_id=str(payload["external_id"]),
            username=str(payload.get("username") or payload["external_id"]),
            first_name=str(
                payload.get("first_name") or payload.get("username") or payload["external_id"]
            ),
            message_text=str(payload["message_text"]),
            source="webhook_simulator",
            inbound_payload=payload.get("inbound_payload"),
        )

    # Generic / universal webhook route — FlowExecutor sequential walk.
    external_id = str(payload.get("external_id") or "").strip()
    message_text = str(payload.get("message_text") or "").strip()
    if not external_id or not message_text:
        return {"status": "ignored", "reason": "missing_external_id_or_text"}

    result = await execute_flow_for_inbound(
        db,
        bot_id=uuid.UUID(bot_id),
        external_id=external_id,
        username=str(payload.get("username") or external_id),
        first_name=str(
            payload.get("first_name") or payload.get("username") or external_id
        ),
        message_text=message_text,
        source=str(payload.get("source") or platform.lower()),
        inbound_payload=payload.get("inbound_payload") or payload.get("body"),
    )

    reply = str(result.get("response_text") or "").strip()
    if reply and not result.get("bot_silent"):
        await _deliver_generic_outbound(
            db,
            bot_id=uuid.UUID(bot_id),
            platform=platform,
            external_id=external_id,
            reply=reply,
            payload=payload,
        )
    return result


async def _deliver_generic_outbound(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    platform: str,
    external_id: str,
    reply: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort outbound for catalog channels without a dedicated messenger adapter."""
    from app.models.core_models import Bot
    from app.services.bot_app_integrations_service import bot_app_integrations_service

    bot = await db.get(Bot, bot_id)
    if bot is None:
        return

    if platform == "JIVO":
        try:
            await bot_app_integrations_service.send_jivo_message(
                bot, client_id=external_id, text=reply
            )
        except Exception as exc:
            logger.warning(
                "WebhookWorker.jivo_outbound_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
        return

    if platform == "WEB_WIDGET":
        try:
            from app.core.redis_client import get_redis_client

            client = get_redis_client()
            key = f"widget:reply:{bot_id}:{external_id}"
            client.lpush(key, reply)
            client.expire(key, 3600)
        except Exception as exc:
            logger.warning(
                "WebhookWorker.widget_reply_store_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )
        return

    if platform == "API":
        callback = None
        body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
        callback = body.get("callback_url") or payload.get("callback_url")
        if callback:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=10.0) as http:
                    await http.post(
                        str(callback),
                        json={
                            "bot_id": str(bot_id),
                            "external_id": external_id,
                            "message_text": reply,
                        },
                    )
            except Exception as exc:
                logger.warning(
                    "WebhookWorker.api_callback_failed | bot_id={bot_id} error={error}",
                    bot_id=bot_id,
                    error=str(exc),
                )
        return

    # CALLS / others — transcript reply stored for ATS callback pull.
    if platform == "CALLS":
        try:
            from app.core.redis_client import get_redis_client

            client = get_redis_client()
            key = f"calls:reply:{bot_id}:{external_id}"
            client.set(key, reply, ex=3600)
        except Exception as exc:
            logger.warning(
                "WebhookWorker.calls_reply_store_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(exc),
            )

