import asyncio
import uuid

from typing import Any

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.core_models import Bot, BotFlow, ChatMessage, Client, MessageSender
from app.core.flow_cache import published_flow_cache
from app.schemas.core_schemas import FlowButton, WebhookSimulateResponse
from app.services.chat_service import broadcast_chat_message
from app.workers.crm_tasks import process_crm_automation_action
from app.tasks.crm_tasks import capture_lead_task
from app.services.flow_parser import FlowExecutor


def _enqueue_crm_action(
    bot_id: uuid.UUID,
    client_id: uuid.UUID,
    action_data: dict[str, Any],
) -> None:
    # Internal native CRM actions are executed inline by FlowExecutor / bridge.
    if str(action_data.get("target") or "").lower() == "internal":
        return
    try:
        process_crm_automation_action.delay(str(bot_id), str(client_id), action_data)
        logger.info(
            "WebhookService.crm_action_queued | bot_id={bot_id} client_id={client_id}",
            bot_id=bot_id,
            client_id=client_id,
        )
    except Exception as exc:
        logger.exception(
            "WebhookService.crm_action_queue_failed | bot_id={bot_id} client_id={client_id} error={error}",
            bot_id=bot_id,
            client_id=client_id,
            error=str(exc),
        )
        asyncio.create_task(
            _run_crm_action_background_fallback(bot_id, client_id, action_data)
        )


def _enqueue_lead_capture(client_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    """Fire-and-forget auto-capture on the ``crm_actions`` Celery queue."""
    try:
        capture_lead_task.apply_async(args=[str(client_id), str(bot_id)])
        logger.info(
            "WebhookService.lead_capture_queued | bot_id={bot_id} client_id={client_id}",
            bot_id=bot_id,
            client_id=client_id,
        )
    except Exception as exc:
        logger.warning(
            "WebhookService.lead_capture_queue_failed | bot_id={bot_id} client_id={client_id} error={error}",
            bot_id=bot_id,
            client_id=client_id,
            error=str(exc),
        )


async def _run_crm_action_background_fallback(
    bot_id: uuid.UUID,
    client_id: uuid.UUID,
    action_data: dict[str, Any],
) -> None:
    from app.services.crm_orchestrator import crm_orchestrator

    try:
        result = await crm_orchestrator.execute_crm_action(bot_id, client_id, action_data)
        logger.info(
            "WebhookService.crm_action_fallback_complete | bot_id={bot_id} client_id={client_id} success={success}",
            bot_id=bot_id,
            client_id=client_id,
            success=result.get("success"),
        )
    except Exception as exc:
        logger.exception(
            "WebhookService.crm_action_fallback_failed | bot_id={bot_id} client_id={client_id} error={error}",
            bot_id=bot_id,
            client_id=client_id,
            error=str(exc),
        )


async def _get_bot(db: AsyncSession, bot_id: uuid.UUID) -> Bot:
    result = await db.execute(
        select(Bot)
        .where(Bot.id == bot_id)
        .options(selectinload(Bot.organization))
    )
    bot = result.scalar_one_or_none()
    if bot is None:
        logger.warning("WebhookService.bot_not_found | bot_id={bot_id}", bot_id=bot_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot with id '{bot_id}' not found.",
        )
    if not bot.is_active:
        logger.warning("WebhookService.bot_inactive | bot_id={bot_id}", bot_id=bot_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Bot with id '{bot_id}' is inactive.",
        )
    return bot





async def _get_or_create_client(
    db: AsyncSession,
    bot_id: uuid.UUID,
    external_id: str,
    username: str,
    first_name: str,
) -> Client:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    display_name = first_name or username or ""
    insert_stmt = pg_insert(Client).values(
        id=uuid.uuid4(),
        bot_id=bot_id,
        external_id=external_id,
        username=username or "",
        first_name=display_name,
        current_step_id="",
        is_paused_by_operator=False,
    )
    stmt = insert_stmt.on_conflict_do_update(
        constraint="uq_clients_bot_external_id",
        set_={
            "username": insert_stmt.excluded.username,
            "first_name": insert_stmt.excluded.first_name,
        },
    ).returning(Client.id)
    try:
        inserted_id = (await db.execute(stmt)).scalar_one()
        await db.flush()
    except Exception:
        # Non-Postgres / missing constraint — fall back to select+insert.
        result = await db.execute(
            select(Client)
            .options(selectinload(Client.bot).selectinload(Bot.user))
            .where(Client.bot_id == bot_id, Client.external_id == external_id)
        )
        client = result.scalar_one_or_none()
        if client is not None:
            if username:
                client.username = username
            if first_name:
                client.first_name = first_name
            return client
        client = Client(
            bot_id=bot_id,
            external_id=external_id,
            username=username or "",
            first_name=display_name,
            current_step_id="",
            is_paused_by_operator=False,
        )
        db.add(client)
        await db.flush()
        inserted_id = client.id

    reload = await db.execute(
        select(Client)
        .options(selectinload(Client.bot).selectinload(Bot.user))
        .where(Client.id == inserted_id)
    )
    client = reload.scalar_one()
    logger.debug(
        "WebhookService.client_upserted | client_id={client_id} external_id={external_id}",
        client_id=client.id,
        external_id=external_id,
    )
    return client


async def _get_latest_published_flow(db: AsyncSession, bot_id: uuid.UUID) -> BotFlow:
    """Load the most recently published flow for live webhook evaluation (no restart required)."""
    cached = published_flow_cache.get(bot_id)
    if cached is not None and cached.is_published:
        flow = BotFlow(
            id=cached.flow_id,
            bot_id=cached.bot_id,
            title=cached.title,
            graph_data=cached.graph_data,
            is_published=True,
            updated_at=cached.updated_at,
        )
        logger.info(
            "WebhookService.flow_cache_hit | bot_id={bot_id} flow_id={flow_id} nodes={nodes}",
            bot_id=bot_id,
            flow_id=flow.id,
            nodes=len(cached.graph_data.get("nodes", [])),
        )
        return flow

    result = await db.execute(
        select(BotFlow)
        .where(
            BotFlow.bot_id == bot_id,
            BotFlow.is_published.is_(True),
        )
        .order_by(BotFlow.updated_at.desc())
        .limit(1)
    )

    flow = result.scalar_one_or_none()

    if flow is None:
        logger.warning("WebhookService.no_published_flow | bot_id={bot_id}", bot_id=bot_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No published flow found for bot '{bot_id}'.",
        )

    await db.refresh(flow)

    graph_data = flow.graph_data if isinstance(flow.graph_data, dict) else {}
    published_flow_cache.put_from_orm(
        flow_id=flow.id,
        bot_id=bot_id,
        title=flow.title,
        graph_data=graph_data,
        is_published=True,
        updated_at=flow.updated_at,
    )

    node_count = len(graph_data.get("nodes", []))
    logger.info(
        "WebhookService.flow_loaded | bot_id={bot_id} flow_id={flow_id} nodes={nodes} updated_at={updated}",
        bot_id=bot_id,
        flow_id=flow.id,
        nodes=node_count,
        updated=flow.updated_at,
    )

    return flow





async def _handle_operator_paused_inbound(

    db: AsyncSession,

    client: Client,

    message_text: str,

    *,

    source: str,

    external_id: str,

    inbound_payload: dict[str, Any] | None,

) -> WebhookSimulateResponse:

    logger.info(

        "WebhookService.operator_paused | client_id={client_id} — bot silent, forwarding to operators",

        client_id=client.id,

    )



    client_message = ChatMessage(

        client_id=client.id,

        sender=MessageSender.CLIENT,

        message_text=message_text,

        payload={

            "source": source,

            "external_id": external_id,

            "operator_paused": True,

            **(inbound_payload or {}),

        },

    )

    db.add(client_message)

    await db.flush()

    _enqueue_lead_capture(client.id, client.bot_id)

    await broadcast_chat_message(client, client_message)



    return WebhookSimulateResponse(

        response_text="",

        buttons=[],

        current_step_id=client.current_step_id,

        bot_silent=True,

        client_id=client.id,

    )





async def process_inbound_message(

    db: AsyncSession,

    bot_id: uuid.UUID,

    external_id: str,

    username: str,

    first_name: str,

    message_text: str,

    *,

    source: str = "webhook",

    inbound_payload: dict[str, Any] | None = None,

) -> WebhookSimulateResponse:

    """Shared orchestration for simulator, Telegram, and future channel webhooks."""

    logger.info(

        "WebhookService.inbound | source={source} bot_id={bot_id} external_id={external_id} message={message!r}",

        source=source,

        bot_id=bot_id,

        external_id=external_id,

        message=message_text,

    )



    bot = await _get_bot(db, bot_id)

    client = await _get_or_create_client(

        db=db,

        bot_id=bot_id,

        external_id=external_id,

        username=username,

        first_name=first_name or username,

    )



    if client.is_paused_by_operator or getattr(client, "conversation_status", "active") == "escalated":

        if not client.is_paused_by_operator:
            client.is_paused_by_operator = True
            client.conversation_status = "escalated"

        return await _handle_operator_paused_inbound(

            db=db,

            client=client,

            message_text=message_text,

            source=source,

            external_id=external_id,

            inbound_payload=inbound_payload,

        )



    flow = await _get_latest_published_flow(db, bot_id)



    graph_data = flow.graph_data if isinstance(flow.graph_data, dict) else {}

    if not graph_data:

        logger.error("WebhookService.empty_graph_data | flow_id={flow_id}", flow_id=flow.id)

        raise HTTPException(

            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,

            detail="Published flow contains empty graph data.",

        )



    executor = FlowExecutor(graph_data)
    bot_config = FlowExecutor.build_bot_config(bot)

    try:
        execution = await executor.execute(
            current_step_id=client.current_step_id,
            incoming_message=message_text,
            context={
                "user_name": first_name or username,
                "channel": source,
                "phone": external_id,
                "external_id": external_id,
                "tags": [],
                "bot_config": bot_config,
            },
            db=db,
            bot_id=bot_id,
            client_id=client.id,
        )
        next_node = execution.to_dict()
    except Exception as exc:
        logger.exception(
            "WebhookService.executor_failed | client_id={client_id} error={error}",
            client_id=client.id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Flow execution failed due to an unexpected error.",
        ) from exc

    previous_step = client.current_step_id
    node_id = str(next_node["node_id"])
    error = next_node.get("error")

    if error == "button_mismatch" and previous_step:
        client.current_step_id = previous_step
    elif node_id == FlowExecutor.WAITING_STEP_ID:
        client.current_step_id = previous_step or node_id
    else:
        client.current_step_id = node_id

    crm_action = next_node.get("crm_action")
    if crm_action and not next_node.get("variables", {}).get("crm_result"):
        # Async fallback queue when executor deferred CRM work.
        _enqueue_crm_action(
            bot_id=bot_id,
            client_id=client.id,
            action_data=crm_action,
        )

    response_text = str(next_node.get("text") or "")
    raw_buttons = next_node.get("buttons") or []
    buttons = [FlowButton.model_validate(btn) for btn in raw_buttons]
    bot_silent = bool(next_node.get("bot_silent"))
    if bot_silent:
        response_text = ""
        buttons = []

    ai_generated = next_node.get("node_type") in {"ai_agent", "llm"}
    ai_payload: dict[str, object] = {}
    media_attachments: list = list(next_node.get("media_attachments") or [])

    if ai_generated:
        node_data = next_node.get("data") or {}
        ai_payload = {
            "generated_by": "flow_parser",
            "knowledge_base_id": node_data.get("knowledge_base_id") if isinstance(node_data, dict) else None,
            "prompt_context_preview": str(
                (node_data.get("prompt_context") if isinstance(node_data, dict) else "") or ""
            )[:200],
            "media_attachment_count": len(media_attachments),
        }
        logger.info(
            "WebhookService.ai_response | client_id={client_id} node_id={node_id}",
            client_id=client.id,
            node_id=next_node.get("node_id"),
        )



    client_message = ChatMessage(

        client_id=client.id,

        sender=MessageSender.CLIENT,

        message_text=message_text,

        payload={

            "source": source,

            "external_id": external_id,

            **(inbound_payload or {}),

        },

    )

    bot_message = ChatMessage(

        client_id=client.id,

        sender=MessageSender.BOT,

        message_text=response_text,

        payload={

            "source": source,

            "node_id": next_node.get("node_id"),

            "node_type": next_node.get("node_type"),

            "buttons": [button.model_dump() for button in buttons],

            "matched_button_id": next_node.get("matched_button_id"),

            "is_waiting": next_node.get("is_waiting", False),

            "is_terminal": next_node.get("is_terminal", False),

            "error": next_node.get("error"),

            "ai_generated": ai_generated,

            **ai_payload,

        },

    )

    db.add(client_message)

    if not bot_silent:

        db.add(bot_message)

    await db.flush()

    _enqueue_lead_capture(client.id, bot_id)

    try:
        bot_row = await db.get(Bot, bot_id)
        if bot_row is not None:
            from app.services.crm_orchestrator import crm_orchestrator

            await crm_orchestrator.handle_new_message_for_crm(
                db,
                bot=bot_row,
                client=client,
                message_text=message_text,
                channel_type=source,
                external_chat_id=external_id,
            )
    except Exception as crm_exc:
        logger.warning(
            "WebhookService.crm_sidecar_failed | client_id={client_id} error={error}",
            client_id=client.id,
            error=str(crm_exc),
        )

    await broadcast_chat_message(client, client_message)

    if response_text and not bot_silent:

        await broadcast_chat_message(client, bot_message)



    logger.info(

        "WebhookService.completed | source={source} client_id={client_id} step={prev} -> {new}",

        source=source,

        client_id=client.id,

        prev=previous_step,

        new=client.current_step_id,

    )



    return WebhookSimulateResponse(

        response_text=response_text,

        buttons=buttons,

        current_step_id=client.current_step_id,

        node_type=next_node.get("node_type"),

        is_waiting=bool(next_node.get("is_waiting")),

        is_terminal=bool(next_node.get("is_terminal")),

        bot_silent=bot_silent,

        client_id=client.id,

        media_attachments=media_attachments,

    )





async def process_simulated_webhook(

    db: AsyncSession,

    bot_id: uuid.UUID,

    external_id: str,

    username: str,

    message_text: str,

) -> WebhookSimulateResponse:

    """Orchestrate client lookup, flow execution, persistence, and response building."""

    return await process_inbound_message(

        db=db,

        bot_id=bot_id,

        external_id=external_id,

        username=username,

        first_name=username,

        message_text=message_text,

        source="webhook_simulator",

    )


