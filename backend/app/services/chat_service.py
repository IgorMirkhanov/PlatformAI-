from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.websocket import WSEventType
from app.core.ws_pubsub import publish_operator_ws_event
from app.models.core_models import Bot, ChatMessage, Client, MessageSender, PlatformType
from app.models.users import User
from app.schemas.core_schemas import (
    ActiveChatSummary,
    ActiveChatsResponse,
    ChatMessageRead,
    ClientInboxProfile,
    CreateCrmDealResponse,
    CrmLinkageCard,
    CrmPlatformLinkage,
    InterceptChatResponse,
    ToggleOperatorResponse,
)


def resolve_state_label(client: Client) -> str:
    if client.is_paused_by_operator:
        return "Waiting for Operator"

    step = (client.current_step_id or "").strip()
    if not step:
        return "New conversation"

    if "ai" in step.lower():
        return "AI Agent mode"

    return f"Step: {step}"


async def _get_client_with_bot(db: AsyncSession, client_id: uuid.UUID) -> Client:
    result = await db.execute(
        select(Client)
        .options(selectinload(Client.bot).selectinload(Bot.user))
        .where(Client.id == client_id)
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client '{client_id}' not found.",
        )
    return client


def _company_id_for_bot(bot: Bot) -> str:
    if bot.organization_id is not None:
        return str(bot.organization_id)
    if bot.user and getattr(bot.user, "company_id", None) is not None:
        return str(bot.user.company_id)
    return str(bot.user_id)


def _operator_session_payload(client: Client) -> dict[str, Any]:
    return {
        "client_id": str(client.id),
        "session_id": str(client.id),
        "bot_id": str(client.bot_id),
        "is_paused_by_operator": client.is_paused_by_operator,
        "state_label": resolve_state_label(client),
        "routing_mode": "operator" if client.is_paused_by_operator else "bot",
    }


async def broadcast_chat_message(
    client: Client,
    message: ChatMessage,
    *,
    company_id: str | None = None,
) -> None:
    """Push inbound/outbound chat metadata to operator WebSocket listeners via Redis."""
    bot = client.bot
    resolved_company = company_id or (_company_id_for_bot(bot) if bot else "default")
    bot_id = str(client.bot_id)

    payload: dict[str, Any] = {
        "client_id": str(client.id),
        "bot_id": bot_id,
        "message": ChatMessageRead.model_validate(message).model_dump(mode="json"),
        "client": {
            "client_id": str(client.id),
            "bot_id": bot_id,
            "external_id": client.external_id,
            "username": client.username,
            "first_name": client.first_name,
            "current_step_id": client.current_step_id,
            "state_label": resolve_state_label(client),
            "is_paused_by_operator": client.is_paused_by_operator,
        },
    }

    # Redis `chat_events` is the single fan-out path (API + Celery workers).
    publish_operator_ws_event(
        company_id=resolved_company,
        event=WSEventType.NEW_MESSAGE.value,
        payload=payload,
        bot_id=bot_id,
    )


async def broadcast_operator_intercept(client: Client) -> None:
    """Publish OPERATOR_INTERCEPT (+ legacy BOT_TOGGLED) on Redis `chat_events`."""
    bot = client.bot
    company_id = _company_id_for_bot(bot) if bot else "default"
    payload = _operator_session_payload(client)
    bot_id = str(client.bot_id)

    publish_operator_ws_event(
        company_id=company_id,
        event=WSEventType.OPERATOR_INTERCEPT.value,
        payload=payload,
        bot_id=bot_id,
    )
    # Legacy alias consumed by older operator clients / caches.
    publish_operator_ws_event(
        company_id=company_id,
        event=WSEventType.BOT_TOGGLED.value,
        payload=payload,
        bot_id=bot_id,
    )


async def broadcast_bot_toggled(client: Client) -> None:
    await broadcast_operator_intercept(client)


_CLOSED_STEP_IDS = frozenset({"closed", "done", "archived", "finished", "resolved"})


def _is_conversation_closed(client: Client) -> bool:
    step = (client.current_step_id or "").strip().lower()
    return step in _CLOSED_STEP_IDS


def _extract_client_phone(client: Client, messages: list[ChatMessage] | None = None) -> str | None:
    source_messages = messages if messages is not None else list(client.messages or [])
    for message in reversed(source_messages):
        payload = message.payload or {}
        phone = payload.get("phone") or payload.get("phone_number")
        if phone:
            return str(phone)
    return None


def _extract_client_tags(bot: Bot) -> list[str]:
    crm = (bot.credentials or {}).get("crm") or {}
    tags: list[str] = []
    for platform in ("amocrm", "bitrix24"):
        config = crm.get(platform) or {}
        for tag in config.get("default_tags") or []:
            tag_text = str(tag).strip()
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
    return tags


def _extract_crm_linkage(bot: Bot, messages: list[ChatMessage]) -> dict[str, Any]:
    crm_config = (bot.credentials or {}).get("crm") or {}
    lead_id: str | None = None
    deal_id: str | None = None

    for message in reversed(messages):
        payload = message.payload or {}
        crm_payload = payload.get("crm") if isinstance(payload.get("crm"), dict) else payload
        if isinstance(crm_payload, dict):
            if crm_payload.get("lead_id") and not lead_id:
                lead_id = str(crm_payload["lead_id"])
            if crm_payload.get("deal_id") and not deal_id:
                deal_id = str(crm_payload["deal_id"])

    def platform_linkage(platform: str) -> dict[str, Any]:
        config = crm_config.get(platform) or {}
        if platform == "amocrm":
            connected = bool(config.get("connected") and config.get("access_token"))
        else:
            connected = bool(config.get("connected") and config.get("webhook_url"))
        stage_label = None
        pipeline_label = None
        if config.get("stage_id"):
            stage_label = f"Stage #{config['stage_id']}"
        if config.get("pipeline_id"):
            pipeline_label = f"Pipeline #{config['pipeline_id']}"
        return {
            "connected": connected,
            "sync_enabled": bool(config.get("sync_enabled", True)) if connected else False,
            "lead_id": lead_id if platform == "amocrm" else None,
            "deal_id": deal_id if platform == "bitrix24" else None,
            "stage_label": stage_label,
            "pipeline_label": pipeline_label,
        }

    return {
        "amocrm": platform_linkage("amocrm"),
        "bitrix24": platform_linkage("bitrix24"),
    }


async def get_active_chats(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None = None,
    include_all: bool = False,
) -> ActiveChatsResponse:
    latest_message_subq = (
        select(
            ChatMessage.client_id.label("client_id"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .group_by(ChatMessage.client_id)
        .subquery()
    )

    stmt = (
        select(Client, Bot, latest_message_subq.c.last_message_at)
        .join(Bot, Client.bot_id == Bot.id)
        .join(latest_message_subq, Client.id == latest_message_subq.c.client_id)
        .where(Bot.deleted_at.is_(None))
        .order_by(latest_message_subq.c.last_message_at.desc())
    )
    if not include_all:
        if organization_id is None:
            return ActiveChatsResponse(chats=[], total=0)
        stmt = stmt.where(Bot.organization_id == organization_id)

    result = await db.execute(stmt)
    rows = result.all()

    summaries: list[ActiveChatSummary] = []
    for client, bot, last_message_at in rows:
        last_msg_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.client_id == client.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        last_message = last_msg_result.scalar_one_or_none()

        summaries.append(
            ActiveChatSummary(
                client_id=client.id,
                bot_id=bot.id,
                bot_name=bot.name,
                platform_type=bot.platform_type,
                external_id=client.external_id,
                username=client.username,
                first_name=client.first_name,
                phone=None,
                tags=_extract_client_tags(bot),
                current_step_id=client.current_step_id,
                state_label=resolve_state_label(client),
                is_paused_by_operator=client.is_paused_by_operator,
                is_closed=_is_conversation_closed(client),
                last_message_text=last_message.message_text if last_message else "",
                last_message_sender=last_message.sender if last_message else None,
                last_message_at=last_message_at,
                unread_count=0,
            )
        )

    return ActiveChatsResponse(chats=summaries, total=len(summaries))


async def get_client_messages(
    db: AsyncSession,
    client_id: uuid.UUID,
) -> list[ChatMessageRead]:
    await _get_client_with_bot(db, client_id)

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.client_id == client_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return [ChatMessageRead.model_validate(message) for message in messages]


async def send_manual_operator_message(
    db: AsyncSession,
    client_id: uuid.UUID,
    message_text: str,
) -> ChatMessageRead:
    client = await _get_client_with_bot(db, client_id)
    bot = client.bot

    operator_message = ChatMessage(
        client_id=client.id,
        sender=MessageSender.OPERATOR,
        message_text=message_text.strip(),
        payload={"source": "operator_panel"},
    )
    db.add(operator_message)
    await db.flush()

    try:
        from app.services.inbound.outbound_router import deliver_outbound, resolve_client_outbound

        normalized = await resolve_client_outbound(db, client=client, bot=bot)
        await deliver_outbound(
            db,
            normalized=normalized,
            reply_text=message_text.strip(),
            payload={"body": normalized.metadata},
            client_id=client.id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "ChatService.outbound_send_failed | client_id={client_id} error={error}",
            client_id=client_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to deliver message to the client channel.",
        ) from exc

    await broadcast_chat_message(client, operator_message)
    return ChatMessageRead.model_validate(operator_message)


async def toggle_operator_pause(
    db: AsyncSession,
    client_id: uuid.UUID,
    paused: bool | None = None,
) -> ToggleOperatorResponse:
    client = await _get_client_with_bot(db, client_id)

    if paused is None:
        client.is_paused_by_operator = not client.is_paused_by_operator
    else:
        client.is_paused_by_operator = paused

    await db.flush()
    await broadcast_bot_toggled(client)

    status_text = "paused" if client.is_paused_by_operator else "resumed"
    logger.info(
        "ChatService.operator_toggle | client_id={client_id} paused={paused}",
        client_id=client_id,
        paused=client.is_paused_by_operator,
    )

    return ToggleOperatorResponse(
        client_id=client.id,
        is_paused_by_operator=client.is_paused_by_operator,
        state_label=resolve_state_label(client),
        message=f"AI bot {status_text} for this client.",
    )


async def intercept_chat_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    action: str | None = None,
) -> InterceptChatResponse:
    """Force operator takeover or release the dialog back to the AI agent."""
    client = await _get_client_with_bot(db, session_id)

    if action == "intercept":
        client.is_paused_by_operator = True
    elif action in {"release", "resume"}:
        client.is_paused_by_operator = False
    else:
        client.is_paused_by_operator = not client.is_paused_by_operator

    await db.flush()
    await broadcast_operator_intercept(client)

    routing_mode = "operator" if client.is_paused_by_operator else "bot"
    if client.is_paused_by_operator:
        message = "Диалог перехвачен оператором. ИИ-агент остановлен для этого клиента."
    else:
        message = "Управление возвращено ИИ-агенту."

    logger.info(
        "ChatService.intercept | session_id={session_id} routing_mode={routing_mode}",
        session_id=session_id,
        routing_mode=routing_mode,
    )

    return InterceptChatResponse(
        session_id=client.id,
        client_id=client.id,
        is_paused_by_operator=client.is_paused_by_operator,
        state_label=resolve_state_label(client),
        routing_mode=routing_mode,
        message=message,
    )


async def resume_chat_session(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> InterceptChatResponse:
    """Explicit resume endpoint: clear operator pause and sync via Redis Pub/Sub."""
    return await intercept_chat_session(db=db, session_id=session_id, action="resume")


async def get_client_inbox_profile(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> ClientInboxProfile:
    client = await _get_client_with_bot(db, session_id)
    bot = client.bot

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.client_id == client.id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = list(result.scalars().all())
    crm_data = _extract_crm_linkage(bot, messages)

    display_name = client.first_name.strip()
    if not display_name and client.username:
        display_name = client.username
    if not display_name:
        display_name = client.external_id

    return ClientInboxProfile(
        client_id=client.id,
        bot_id=bot.id,
        bot_name=bot.name,
        platform_type=bot.platform_type,
        display_name=display_name,
        phone=_extract_client_phone(client, messages),
        username=client.username,
        external_id=client.external_id,
        tags=_extract_client_tags(bot),
        is_paused_by_operator=client.is_paused_by_operator,
        state_label=resolve_state_label(client),
        is_closed=_is_conversation_closed(client),
        crm=CrmLinkageCard(
            amocrm=CrmPlatformLinkage(**crm_data["amocrm"]),
            bitrix24=CrmPlatformLinkage(**crm_data["bitrix24"]),
        ),
    )


async def create_crm_deal_for_client(
    db: AsyncSession,
    session_id: uuid.UUID,
) -> CreateCrmDealResponse:
    from app.services.crm_orchestrator import crm_orchestrator

    client = await _get_client_with_bot(db, session_id)
    bot = client.bot
    crm_config = (bot.credentials or {}).get("crm") or {}

    platform = "amocrm"
    if crm_config.get("bitrix24", {}).get("connected"):
        platform = "bitrix24"
    elif crm_config.get("amocrm", {}).get("connected"):
        platform = "amocrm"
    else:
        return CreateCrmDealResponse(
            success=False,
            message="CRM не подключена для этого агента.",
        )

    config = crm_config.get(platform) or {}
    action_data: dict[str, Any] = {
        "platform": platform,
        "pipeline_id": config.get("pipeline_id"),
        "stage_id": config.get("stage_id"),
        "tags": config.get("default_tags") or [],
    }

    result = await crm_orchestrator.execute_crm_action(
        bot_id=bot.id,
        client_id=client.id,
        action_data=action_data,
    )

    if not result.get("success"):
        return CreateCrmDealResponse(
            success=False,
            platform=platform,
            message=str(result.get("error") or "Не удалось создать сделку в CRM."),
        )

    lead_id = result.get("lead_id")
    deal_id = result.get("deal_id")
    crm_note = {
        "crm": {
            "platform": platform,
            "lead_id": lead_id,
            "deal_id": deal_id,
        }
    }
    db.add(
        ChatMessage(
            client_id=client.id,
            sender=MessageSender.OPERATOR,
            message_text=f"Сделка создана в CRM ({platform}).",
            payload=crm_note,
        )
    )
    await db.flush()

    return CreateCrmDealResponse(
        success=True,
        platform=platform,
        lead_id=str(lead_id) if lead_id is not None else None,
        deal_id=str(deal_id) if deal_id is not None else None,
        message="Сделка успешно создана в CRM.",
    )


async def resolve_operator_company(db: AsyncSession, operator_id: uuid.UUID) -> str:
    result = await db.execute(select(User).where(User.id == operator_id))
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning(
            "ChatService.unknown_operator | operator_id={operator_id} — using default company",
            operator_id=operator_id,
        )
        return "default"
    if getattr(user, "company_id", None) is not None:
        return str(user.company_id)
    return str(user.id)
