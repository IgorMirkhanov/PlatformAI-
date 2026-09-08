from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.flow_cache import published_flow_cache
from app.core.llm_cache import llm_response_cache
from app.core.rag_cache import rag_activation_cache
from app.core.security import encrypt_credential, hash_bot_token
from app.models.core_models import Bot, BotFlow, PlatformType, UserRole
from app.models.users import User
from app.schemas.core_schemas import (
    AgentUseCaseTemplate,
    BotAgentProfileRead,
    BotAvatarUploadResponse,
    BotChannelsResponse,
    BotFlowResponse,
    BotFunctionsUpdate,
    BotHealthListResponse,
    BotHealthTelemetry,
    BotLLMConfigUpdate,
    BotPromptingUpdate,
    BotSettingsUpdate,
    EnhancePromptRequest,
    EnhancePromptResponse,
    OptimizePromptRequest,
    OptimizePromptResponse,
    ChannelIntegrationType,
    ChannelStatusItem,
    CreateBotRequest,
    CreateBotResponse,
    FlowGraphData,
    PublishBotFlowRequest,
    PublishBotFlowResponse,
    SaveBotFlowRequest,
    SetupChannelRequest,
    SetupChannelResponse,
    TelegramSetupRequest,
    TelegramSetupResponse,
    generate_whatsapp_verify_token,
)
from app.schemas.graph_validation import GraphValidationError, issues_to_http_detail
from app.schemas.knowledge_base_schemas import BotKnowledgeToggleResponse
from app.services.knowledge_base_service import knowledge_base_service
from app.services.prompt_optimization_service import prompt_optimization_service
from app.services.sandbox_service import sandbox_service
from app.services.telegram_service import telegram_service


DEFAULT_FLOW_GRAPH: dict[str, object] = {
    "nodes": [
        {
            "id": "welcome_node",
            "type": "text_message",
            "data": {
                "text": "Welcome! How can we help you today?",
                "buttons": [],
            },
        }
    ],
    "edges": [],
}

USE_CASE_TEMPLATES: dict[AgentUseCaseTemplate, dict[str, object]] = {
    AgentUseCaseTemplate.SUPPORT_RAG: {
        "flow_title": "Техподдержка — стартовый сценарий",
        "welcome_text": (
            "Здравствуйте! Я ассистент техподдержки. "
            "Опишите вашу проблему — я помогу найти ответ в базе знаний."
        ),
        "prompt_instructions": (
            "Ты вежливый ассистент техподдержки. Отвечай кратко и по делу, "
            "используй базу знаний (RAG) для точных инструкций и эскалируй сложные "
            "случаи оператору."
        ),
    },
    AgentUseCaseTemplate.SALES_CRM: {
        "flow_title": "Продажи и CRM — стартовый сценарий",
        "welcome_text": (
            "Добро пожаловать! Я помогу подобрать решение, оформить заявку "
            "и передать контакт менеджеру в CRM."
        ),
        "prompt_instructions": (
            "Ты ассистент отдела продаж. Выясняй потребности клиента, предлагай "
            "релевантные продукты и фиксируй лид для CRM. Будь проактивным и дружелюбным."
        ),
    },
    AgentUseCaseTemplate.EMPTY: {
        "flow_title": "Базовый сценарий",
        "welcome_text": "Здравствуйте! Чем могу помочь?",
        "prompt_instructions": "Ты полезный ИИ-ассистент.",
    },
}

AVATAR_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_AVATAR_BYTES = 5 * 1024 * 1024

OMNICHANNEL_DEFINITIONS: tuple[ChannelIntegrationType, ...] = (
    ChannelIntegrationType.TELEGRAM,
    ChannelIntegrationType.WHATSAPP,
    ChannelIntegrationType.INSTAGRAM,
    ChannelIntegrationType.VKONTAKTE,
    ChannelIntegrationType.WEB_WIDGET,
)


class BotManagementService:
    """Lifecycle management for bots, channel credentials, and published flows."""

    async def create_bot(
        self,
        db: AsyncSession,
        payload: CreateBotRequest,
        *,
        current_user: User | None = None,
    ) -> CreateBotResponse:
        if payload.platform_type not in {PlatformType.TELEGRAM, PlatformType.WHATSAPP}:
            raise ValueError(
                f"Platform '{payload.platform_type.value}' is not supported for create yet."
            )

        user = current_user or await self._resolve_user(db, payload.user_id)
        from app.services.team_service import team_service

        await team_service._ensure_primary_company(db, user)
        organization_id = user.company_id
        if organization_id is None:
            raise ValueError("Authenticated user is not bound to an organization.")

        from app.services.quota_service import QuotaExceeded, quota_service

        try:
            await quota_service.assert_can_create_bot(db, organization_id)
        except QuotaExceeded as exc:
            quota_service.raise_http(exc)

        # Inactive by default until channels + flow are configured.
        bot = Bot(
            user_id=user.id,
            organization_id=organization_id,
            name=payload.name.strip() or "New Agent",
            platform_type=payload.platform_type,
            is_active=False,
            credentials={},
            created_by_id=user.id,
        )
        db.add(bot)
        await db.flush()

        template = USE_CASE_TEMPLATES.get(
            payload.use_case,
            USE_CASE_TEMPLATES[AgentUseCaseTemplate.EMPTY],
        )
        bot.prompt_instructions = str(template.get("prompt_instructions") or "")
        bot.llm_model_name = "gpt-4o-mini"
        bot.llm_temperature = 0.7

        # Prefer seeded template graph; empty use-case defaults to {}.
        compiled_graph: dict[str, object] = {}
        if payload.use_case != AgentUseCaseTemplate.EMPTY:
            welcome_text = template.get("welcome_text")
            if welcome_text:
                compiled_graph = {
                    "nodes": [
                        {
                            "id": "welcome_node",
                            "type": "text_message",
                            "data": {
                                "text": str(welcome_text),
                                "buttons": [],
                            },
                        }
                    ],
                    "edges": [],
                }

        graph_dump: dict[str, object]
        is_published = False
        if compiled_graph:
            validated_graph = FlowGraphData.model_validate(compiled_graph)
            graph_dump = validated_graph.model_dump(mode="json")
            is_published = True
        else:
            graph_dump = {}

        flow = BotFlow(
            bot_id=bot.id,
            title=str(template.get("flow_title") or "Draft flow"),
            graph_data=graph_dump,
            is_published=is_published,
        )
        db.add(flow)
        await db.flush()

        published_flow_cache.invalidate(bot.id)
        if is_published:
            published_flow_cache.put_from_orm(
                flow_id=flow.id,
                bot_id=bot.id,
                title=flow.title,
                graph_data=graph_dump,
                is_published=True,
                updated_at=flow.updated_at,
            )

        logger.info(
            "BotManagement.created | bot_id={bot_id} organization_id={organization_id} "
            "platform={platform} use_case={use_case} status=inactive",
            bot_id=bot.id,
            organization_id=organization_id,
            platform=bot.platform_type.value,
            use_case=payload.use_case.value,
        )

        return CreateBotResponse(
            bot_id=bot.id,
            name=bot.name,
            platform_type=bot.platform_type,
            is_active=bot.is_active,
        )

    async def save_bot_flow(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: SaveBotFlowRequest,
    ) -> PublishBotFlowResponse:
        bot = await self._get_bot(db, bot_id)
        graph_dump = payload.resolve_graph_payload()
        now = datetime.now(timezone.utc)

        flow_result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == bot_id)
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        flow = flow_result.scalar_one_or_none()

        # Save is always draft — publishing is exclusive to /publish.
        if flow is None:
            flow = BotFlow(
                bot_id=bot_id,
                title=payload.title,
                graph_data=graph_dump,
                is_published=False,
                updated_at=now,
            )
            db.add(flow)
        else:
            flow.title = payload.title
            flow.graph_data = graph_dump
            flow.updated_at = now
            flag_modified(flow, "graph_data")

        await db.flush()
        await db.refresh(flow)

        logger.info(
            "BotManagement.saved_flow | bot_id={bot_id} flow_id={flow_id} nodes={nodes} published={published}",
            bot_id=bot.id,
            flow_id=flow.id,
            nodes=len(graph_dump.get("nodes") or []),
            published=flow.is_published,
        )

        return PublishBotFlowResponse(
            bot_id=bot_id,
            flow_id=flow.id,
            title=flow.title,
            is_published=flow.is_published,
            node_count=len(graph_dump.get("nodes") or []),
            edge_count=len(graph_dump.get("edges") or []),
            message="Flow saved successfully.",
        )

    async def publish_bot_flow(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: PublishBotFlowRequest,
    ) -> PublishBotFlowResponse:
        bot = await self._get_bot(db, bot_id)

        try:
            # Re-validate so ConditionNodeData / ApiRequestNodeData nested fields
            # are normalized before JSONB persistence.
            validated_graph = FlowGraphData.model_validate(payload.compiled_graph_dump())
        except GraphValidationError as exc:
            raise exc
        except ValidationError as exc:
            raise ValueError(f"Invalid graph payload: {exc}") from exc

        flow_result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == bot_id)
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        flow = flow_result.scalar_one_or_none()

        graph_dump = validated_graph.model_dump(mode="json")
        now = datetime.now(timezone.utc)

        if flow is None:
            flow = BotFlow(
                bot_id=bot_id,
                title=payload.title,
                graph_data=graph_dump,
                is_published=True,
                updated_at=now,
            )
            db.add(flow)
        else:
            flow.title = payload.title
            flow.graph_data = graph_dump
            flow.is_published = True
            flow.updated_at = now
            flag_modified(flow, "graph_data")

        await db.flush()
        await db.refresh(flow)

        from app.services.flow_version_service import flow_version_service

        await flow_version_service.snapshot_on_publish(db, bot_id=bot_id, flow=flow)

        # Drop stale compiled graphs so the execution engine loads this revision.
        published_flow_cache.invalidate(bot_id)
        published_flow_cache.put_from_orm(
            flow_id=flow.id,
            bot_id=bot_id,
            title=flow.title,
            graph_data=graph_dump,
            is_published=True,
            updated_at=flow.updated_at,
        )
        # Node prompt_context changes invalidate Redis LLM exact-match answers.
        await llm_response_cache.invalidate_bot_cache(bot_id)
        # Reset sandbox conversation cursors so they start on the new graph.
        sandbox_service.clear_session(bot_id)

        logger.info(
            "BotManagement.published | bot_id={bot_id} flow_id={flow_id} nodes={nodes} updated_at={updated}",
            bot_id=bot_id,
            flow_id=flow.id,
            nodes=len(validated_graph.nodes),
            updated=flow.updated_at,
        )

        return PublishBotFlowResponse(
            bot_id=bot_id,
            flow_id=flow.id,
            title=flow.title,
            is_published=flow.is_published,
            node_count=len(validated_graph.nodes),
            edge_count=len(validated_graph.edges),
            message="Сценарий успешно скомпилирован и опубликован!",
        )

    async def get_bot_flow(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> BotFlowResponse:
        await self._get_bot(db, bot_id)

        published_result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == bot_id, BotFlow.is_published.is_(True))
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        flow = published_result.scalar_one_or_none()

        if flow is None:
            saved_result = await db.execute(
                select(BotFlow)
                .where(BotFlow.bot_id == bot_id)
                .order_by(BotFlow.updated_at.desc())
                .limit(1)
            )
            flow = saved_result.scalar_one_or_none()

        if flow is not None:
            raw_graph = flow.graph_data if isinstance(flow.graph_data, dict) else {}
            try:
                graph = FlowGraphData.model_validate(raw_graph)
                graph_payload = graph.model_dump(mode="json")
                is_default = False
            except (GraphValidationError, ValidationError) as exc:
                logger.warning(
                    "BotManagement.flow_soft_load | bot_id={bot_id} flow_id={flow_id} error={error}",
                    bot_id=bot_id,
                    flow_id=flow.id,
                    error=str(exc),
                )
                # Prefer stored draft payload over wiping the canvas with a template.
                if raw_graph.get("nodes"):
                    graph_payload = {
                        "nodes": raw_graph.get("nodes") or [],
                        "edges": raw_graph.get("edges") or [],
                    }
                    is_default = False
                else:
                    graph_payload = DEFAULT_FLOW_GRAPH
                    is_default = True

            return BotFlowResponse(
                bot_id=bot_id,
                flow_id=flow.id,
                title=flow.title,
                graph_data=graph_payload,
                is_published=flow.is_published,
                is_default_template=is_default,
                updated_at=flow.updated_at,
            )

        logger.info(
            "BotManagement.flow_default_template | bot_id={bot_id}",
            bot_id=bot_id,
        )
        return BotFlowResponse(
            bot_id=bot_id,
            flow_id=None,
            title="Default Welcome Flow",
            graph_data=DEFAULT_FLOW_GRAPH,
            is_published=False,
            is_default_template=True,
            updated_at=None,
        )

    async def setup_channel(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: SetupChannelRequest,
    ) -> SetupChannelResponse:
        bot = await self._get_bot(db, bot_id)

        if payload.channel_type is not None:
            return await self._setup_omnichannel(db, bot, payload)

        if bot.platform_type == PlatformType.TELEGRAM:
            return await self._setup_telegram_channel(
                db,
                bot,
                payload,
                channel_type=ChannelIntegrationType.TELEGRAM,
            )

        if bot.platform_type == PlatformType.WHATSAPP:
            return await self._setup_whatsapp_channel(
                db,
                bot,
                payload,
                channel_type=ChannelIntegrationType.WHATSAPP,
            )

        raise ValueError(f"Unsupported platform '{bot.platform_type.value}'.")

    async def get_bot_channels(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> BotChannelsResponse:
        bot = await self._get_bot(db, bot_id)
        credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
        channels_map = self._normalize_channels_map(credentials, bot_id=bot.id)

        items: list[ChannelStatusItem] = []
        for channel_type in OMNICHANNEL_DEFINITIONS:
            entry = channels_map.get(channel_type.value, {})
            connected = bool(entry.get("connected"))
            active = bool(entry.get("active", connected))
            webhook_url = entry.get("webhook_url")
            verify_token = entry.get("verify_token") or entry.get("whatsapp_verify_token")
            embed_script = self._build_widget_embed_script(bot.id) if channel_type == ChannelIntegrationType.WEB_WIDGET else None
            metadata: dict[str, str] = {}
            if entry.get("instagram_page_id"):
                metadata["instagram_page_id"] = str(entry["instagram_page_id"])
            if entry.get("vk_group_id"):
                metadata["vk_group_id"] = str(entry["vk_group_id"])
            if entry.get("whatsapp_business_account_id"):
                metadata["whatsapp_business_account_id"] = str(entry["whatsapp_business_account_id"])
            if entry.get("whatsapp_phone_number_id"):
                metadata["whatsapp_phone_number_id"] = str(entry["whatsapp_phone_number_id"])

            items.append(
                ChannelStatusItem(
                    channel_type=channel_type,
                    connected=connected,
                    active=active and connected,
                    webhook_url=str(webhook_url) if webhook_url else None,
                    verify_token=str(verify_token) if verify_token else None,
                    embed_script=embed_script if connected or channel_type == ChannelIntegrationType.WEB_WIDGET else embed_script,
                    telegram_username=str(entry["telegram_username"])
                    if entry.get("telegram_username")
                    else None,
                    metadata=metadata,
                )
            )

        return BotChannelsResponse(bot_id=bot.id, channels=items)

    async def _setup_omnichannel(
        self,
        db: AsyncSession,
        bot: Bot,
        payload: SetupChannelRequest,
    ) -> SetupChannelResponse:
        channel_type = payload.channel_type
        if channel_type is None:
            raise ValueError("channel_type is required for omnichannel setup.")

        if channel_type == ChannelIntegrationType.TELEGRAM:
            return await self._setup_telegram_channel(db, bot, payload, channel_type=channel_type)
        if channel_type == ChannelIntegrationType.WHATSAPP:
            return await self._setup_whatsapp_channel(db, bot, payload, channel_type=channel_type)
        if channel_type == ChannelIntegrationType.INSTAGRAM:
            return await self._setup_instagram_channel(db, bot, payload)
        if channel_type == ChannelIntegrationType.VKONTAKTE:
            return await self._setup_vkontakte_channel(db, bot, payload)
        if channel_type == ChannelIntegrationType.WEB_WIDGET:
            return await self._setup_web_widget_channel(db, bot, payload)

        raise ValueError(f"Unsupported channel type '{channel_type.value}'.")

    async def _setup_telegram_channel(
        self,
        db: AsyncSession,
        bot: Bot,
        payload: SetupChannelRequest,
        channel_type: ChannelIntegrationType,
    ) -> SetupChannelResponse:
        if not payload.telegram_bot_token:
            raise ValueError("telegram_bot_token is required for Telegram bots.")

        token = payload.telegram_bot_token.strip()
        token_hash = hash_bot_token(token)
        telegram_info = await telegram_service.verify_bot_token(token)
        webhook_url, webhook_secret = await telegram_service.register_webhook(token, token_hash)
        delivery_mode = telegram_service.telegram_delivery_mode(webhook_url)
        active = payload.telegram_active if payload.telegram_active is not None else True

        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        channels[channel_type.value] = {
            "connected": True,
            "active": active,
            "telegram_bot_token": encrypt_credential(token),
            "token_hash": token_hash,
            "telegram_username": telegram_info.get("username"),
            "webhook_url": webhook_url,
            "webhook_secret_token": webhook_secret,
            "delivery_mode": delivery_mode,
            "channel": channel_type.value,
        }
        credentials["channels"] = channels
        credentials.update(
            {
                "telegram_bot_token": encrypt_credential(token),
                "token_hash": token_hash,
                "telegram_username": telegram_info.get("username"),
                "channel": channel_type.value,
                "webhook_url": webhook_url,
                "webhook_secret_token": webhook_secret,
                "delivery_mode": delivery_mode,
            }
        )
        bot.credentials = credentials
        bot.is_active = active
        await db.flush()

        connected_message = (
            "Telegram подключён в локальном polling-режиме."
            if delivery_mode == "polling"
            else "Telegram webhook registered successfully."
        )
        return SetupChannelResponse(
            bot_id=bot.id,
            platform_type=bot.platform_type,
            channel_type=channel_type,
            channel_connected=True,
            channel_active=active,
            webhook_url=webhook_url,
            token_hash=token_hash,
            telegram_username=str(telegram_info.get("username"))
            if telegram_info.get("username")
            else None,
            message=connected_message,
        )

    async def _setup_whatsapp_channel(
        self,
        db: AsyncSession,
        bot: Bot,
        payload: SetupChannelRequest,
        channel_type: ChannelIntegrationType,
    ) -> SetupChannelResponse:
        if not payload.whatsapp_phone_number_id or not payload.whatsapp_access_token:
            raise ValueError(
                "whatsapp_phone_number_id and whatsapp_access_token are required for WhatsApp."
            )

        business_account_id = (payload.whatsapp_business_account_id or "").strip()
        if payload.channel_type == ChannelIntegrationType.WHATSAPP and not business_account_id:
            raise ValueError("whatsapp_business_account_id is required for WhatsApp Business API.")

        access_token = payload.whatsapp_access_token.strip()
        token_hash = hash_bot_token(access_token)
        verify_token = (payload.whatsapp_verify_token or generate_whatsapp_verify_token()).strip()
        webhook_url = (
            f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/whatsapp/{bot.id}"
        )

        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        channels[channel_type.value] = {
            "connected": True,
            "active": True,
            "whatsapp_phone_number_id": payload.whatsapp_phone_number_id.strip(),
            "whatsapp_business_account_id": business_account_id or None,
            "whatsapp_access_token": encrypt_credential(access_token),
            "whatsapp_verify_token": verify_token,
            "verify_token": verify_token,
            "token_hash": token_hash,
            "channel": channel_type.value,
            "webhook_url": webhook_url,
        }
        credentials["channels"] = channels
        credentials.update(
            {
                "whatsapp_phone_number_id": payload.whatsapp_phone_number_id.strip(),
                "whatsapp_business_account_id": business_account_id or None,
                "whatsapp_access_token": encrypt_credential(access_token),
                "whatsapp_verify_token": verify_token,
                "token_hash": token_hash,
                "channel": channel_type.value,
                "webhook_url": webhook_url,
            }
        )
        bot.credentials = credentials
        bot.is_active = True
        await db.flush()

        logger.info(
            "BotManagement.whatsapp_configured | bot_id={bot_id} webhook={url}",
            bot_id=bot.id,
            url=webhook_url,
        )

        return SetupChannelResponse(
            bot_id=bot.id,
            platform_type=bot.platform_type,
            channel_type=channel_type,
            channel_connected=True,
            channel_active=True,
            webhook_url=webhook_url,
            token_hash=token_hash,
            verify_token=verify_token,
            message="WhatsApp Business API credentials stored and webhook endpoint mapped.",
        )

    async def _setup_instagram_channel(
        self,
        db: AsyncSession,
        bot: Bot,
        payload: SetupChannelRequest,
    ) -> SetupChannelResponse:
        page_id = (payload.instagram_page_id or "").strip()
        access_token = (payload.instagram_access_token or "").strip()
        if not page_id or not access_token:
            raise ValueError(
                "instagram_page_id and instagram_access_token are required for Instagram Direct."
            )

        token_hash = hash_bot_token(access_token)
        webhook_url = (
            f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/instagram/{token_hash}"
        )
        verify_token = generate_whatsapp_verify_token()

        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        channels[ChannelIntegrationType.INSTAGRAM.value] = {
            "connected": True,
            "active": True,
            "instagram_page_id": page_id,
            "instagram_access_token": encrypt_credential(access_token),
            "token_hash": token_hash,
            "verify_token": verify_token,
            "webhook_url": webhook_url,
            "channel": ChannelIntegrationType.INSTAGRAM.value,
        }
        credentials["channels"] = channels
        bot.credentials = credentials
        bot.is_active = True
        await db.flush()

        return SetupChannelResponse(
            bot_id=bot.id,
            platform_type=bot.platform_type,
            channel_type=ChannelIntegrationType.INSTAGRAM,
            channel_connected=True,
            channel_active=True,
            webhook_url=webhook_url,
            token_hash=token_hash,
            verify_token=verify_token,
            message="Instagram Direct credentials stored and webhook endpoint mapped.",
        )

    async def _setup_vkontakte_channel(
        self,
        db: AsyncSession,
        bot: Bot,
        payload: SetupChannelRequest,
    ) -> SetupChannelResponse:
        group_id = (payload.vk_group_id or "").strip()
        access_token = (payload.vk_access_token or "").strip()
        if not group_id or not access_token:
            raise ValueError("vk_group_id and vk_access_token are required for VKontakte.")

        token_hash = hash_bot_token(access_token)
        webhook_url = (
            f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/vkontakte/{token_hash}"
        )

        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        channels[ChannelIntegrationType.VKONTAKTE.value] = {
            "connected": True,
            "active": True,
            "vk_group_id": group_id,
            "vk_access_token": encrypt_credential(access_token),
            "token_hash": token_hash,
            "webhook_url": webhook_url,
            "channel": ChannelIntegrationType.VKONTAKTE.value,
        }
        credentials["channels"] = channels
        bot.credentials = credentials
        bot.is_active = True
        await db.flush()

        return SetupChannelResponse(
            bot_id=bot.id,
            platform_type=bot.platform_type,
            channel_type=ChannelIntegrationType.VKONTAKTE,
            channel_connected=True,
            channel_active=True,
            webhook_url=webhook_url,
            token_hash=token_hash,
            message="VKontakte community connector configured.",
        )

    async def _setup_web_widget_channel(
        self,
        db: AsyncSession,
        bot: Bot,
        payload: SetupChannelRequest,
    ) -> SetupChannelResponse:
        active = payload.web_widget_active if payload.web_widget_active is not None else True
        embed_script = self._build_widget_embed_script(bot.id)

        credentials = dict(bot.credentials or {})
        channels = dict(credentials.get("channels") or {})
        channels[ChannelIntegrationType.WEB_WIDGET.value] = {
            "connected": True,
            "active": active,
            "widget_id": str(bot.id),
            "embed_script": embed_script,
            "channel": ChannelIntegrationType.WEB_WIDGET.value,
        }
        credentials["channels"] = channels
        bot.credentials = credentials
        if active:
            bot.is_active = True
        await db.flush()

        return SetupChannelResponse(
            bot_id=bot.id,
            platform_type=bot.platform_type,
            channel_type=ChannelIntegrationType.WEB_WIDGET,
            channel_connected=True,
            channel_active=active,
            embed_script=embed_script,
            message="Embeddable web widget enabled for external deployment.",
        )

    def _build_widget_embed_script(self, bot_id: uuid.UUID) -> str:
        base = settings.WEBHOOK_BASE_URL.rstrip("/")
        if "8000" in base or base.startswith("http://localhost"):
            widget_origin = "http://localhost:3000"
        else:
            widget_origin = base
        return f'<script src="{widget_origin}/widget.js?id={bot_id}" async></script>'

    def _normalize_channels_map(
        self,
        credentials: dict[str, object],
        bot_id: uuid.UUID,
    ) -> dict[str, dict[str, object]]:
        channels: dict[str, dict[str, object]] = {}
        raw = credentials.get("channels")
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, dict):
                    channels[str(key)] = dict(value)

        legacy_channel = credentials.get("channel")
        if credentials.get("token_hash") and legacy_channel == "telegram" and "telegram" not in channels:
            channels["telegram"] = {
                "connected": True,
                "active": True,
                "token_hash": credentials.get("token_hash"),
                "telegram_username": credentials.get("telegram_username"),
                "webhook_url": credentials.get("webhook_url")
                or (
                    f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/telegram/"
                    f"{credentials['token_hash']}"
                ),
            }
        if credentials.get("token_hash") and legacy_channel == "whatsapp" and "whatsapp" not in channels:
            channels["whatsapp"] = {
                "connected": True,
                "active": True,
                "token_hash": credentials.get("token_hash"),
                "webhook_url": credentials.get("webhook_url"),
                "whatsapp_phone_number_id": credentials.get("whatsapp_phone_number_id"),
                "whatsapp_business_account_id": credentials.get("whatsapp_business_account_id"),
                "verify_token": credentials.get("whatsapp_verify_token"),
            }

        if ChannelIntegrationType.WEB_WIDGET.value not in channels:
            channels[ChannelIntegrationType.WEB_WIDGET.value] = {
                "connected": False,
                "active": False,
                "embed_script": self._build_widget_embed_script(bot_id),
            }

        return channels

    async def setup_telegram_legacy(
        self,
        db: AsyncSession,
        payload: TelegramSetupRequest,
        *,
        current_user: User | None = None,
    ) -> TelegramSetupResponse:
        create_response = await self.create_bot(
            db,
            CreateBotRequest(
                name=payload.bot_name,
                platform_type=PlatformType.TELEGRAM,
                user_id=(current_user.id if current_user is not None else payload.user_id),
            ),
            current_user=current_user,
        )
        channel_response = await self.setup_channel(
            db,
            create_response.bot_id,
            SetupChannelRequest(telegram_bot_token=payload.bot_token),
        )
        bot = await self._get_bot(db, create_response.bot_id)
        username = (bot.credentials or {}).get("telegram_username")

        return TelegramSetupResponse(
            bot_id=create_response.bot_id,
            bot_name=create_response.name,
            token_hash=channel_response.token_hash or "",
            webhook_url=channel_response.webhook_url or "",
            telegram_username=str(username) if username else None,
        )

    async def get_bot_health(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> BotHealthTelemetry:
        bot = await self._get_bot(db, bot_id)
        return await self._build_health_telemetry(db, bot)

    async def list_bots_health(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None = None,
        include_all: bool = False,
    ) -> BotHealthListResponse:
        stmt = select(Bot).where(Bot.deleted_at.is_(None)).order_by(Bot.name.asc())
        if not include_all:
            if organization_id is None:
                return BotHealthListResponse(bots=[], total=0)
            stmt = stmt.where(Bot.organization_id == organization_id)
        result = await db.execute(stmt)
        bots = result.scalars().all()
        telemetry = [await self._build_health_telemetry(db, bot) for bot in bots]
        return BotHealthListResponse(bots=telemetry, total=len(telemetry))

    async def _build_health_telemetry(
        self,
        db: AsyncSession,
        bot: Bot,
    ) -> BotHealthTelemetry:
        credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
        channel_connected = bool(credentials.get("token_hash"))

        flow_result = await db.execute(
            select(BotFlow)
            .where(BotFlow.bot_id == bot.id, BotFlow.is_published.is_(True))
            .order_by(BotFlow.updated_at.desc())
            .limit(1)
        )
        flow = flow_result.scalar_one_or_none()

        node_count = 0
        edge_count = 0
        validation_status = "missing"
        issues = []

        if flow and isinstance(flow.graph_data, dict):
            node_count = len(flow.graph_data.get("nodes", []))
            edge_count = len(flow.graph_data.get("edges", []))
            try:
                FlowGraphData.model_validate(flow.graph_data)
                validation_status = "valid"
            except GraphValidationError as exc:
                validation_status = "invalid"
                issues = exc.issues
            except ValidationError:
                validation_status = "invalid"

        webhook_url = credentials.get("webhook_url")
        if not webhook_url and credentials.get("token_hash") and bot.platform_type == PlatformType.TELEGRAM:
            webhook_url = (
                f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/telegram/"
                f"{credentials['token_hash']}"
            )

        return BotHealthTelemetry(
            bot_id=bot.id,
            bot_name=bot.name,
            platform_type=bot.platform_type,
            is_active=bot.is_active,
            channel_connected=channel_connected,
            flow_published=flow is not None,
            validation_status=validation_status,
            node_count=node_count,
            edge_count=edge_count,
            flow_updated_at=flow.updated_at if flow else None,
            webhook_url=str(webhook_url) if webhook_url else None,
            issues=issues,
        )

    async def update_bot_settings(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: BotSettingsUpdate,
    ) -> BotAgentProfileRead:
        bot = await self._get_bot(db, bot_id)
        updates = payload.model_dump(exclude_unset=True)

        if "schedule_config" in updates and updates["schedule_config"] is not None:
            schedule = updates["schedule_config"]
            if hasattr(schedule, "model_dump"):
                updates["schedule_config"] = schedule.model_dump()

        for field, value in updates.items():
            setattr(bot, field, value)

        await self._sync_telegram_webhook_on_activation(db, bot, updates)

        await db.flush()
        await db.refresh(bot)
        logger.info("BotManagement.settings_updated | bot_id={bot_id}", bot_id=bot_id)
        return BotAgentProfileRead.model_validate(bot)

    async def _sync_telegram_webhook_on_activation(
        self,
        db: AsyncSession,
        bot: Bot,
        updates: dict[str, Any],
    ) -> None:
        """Register Telegram setWebhook when the bot is activated in the admin panel."""
        if updates.get("is_active") is not True:
            return
        credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
        channels = credentials.get("channels") if isinstance(credentials.get("channels"), dict) else {}
        telegram = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
        token_hash = str(credentials.get("token_hash") or telegram.get("token_hash") or "").strip()
        if not token_hash:
            return
        try:
            token = telegram_service.extract_bot_token(bot)
        except ValueError:
            logger.warning(
                "BotManagement.telegram_webhook_skip | bot_id={bot_id} reason=no_token",
                bot_id=bot.id,
            )
            return
        try:
            webhook_url, _secret = await telegram_service.register_webhook(token, token_hash)
            logger.info(
                "BotManagement.telegram_webhook_registered | bot_id={bot_id} url={url}",
                bot_id=bot.id,
                url=webhook_url,
            )
        except Exception as exc:
            logger.warning(
                "BotManagement.telegram_webhook_failed | bot_id={bot_id} error={error}",
                bot_id=bot.id,
                error=str(exc),
            )

    async def upload_bot_avatar(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        file: UploadFile,
    ) -> BotAvatarUploadResponse:
        bot = await self._get_bot(db, bot_id)

        content_type = (file.content_type or "").lower()
        extension = AVATAR_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise ValueError("Unsupported image type. Use JPEG, PNG, WebP, or GIF.")

        raw = await file.read()
        if not raw:
            raise ValueError("Empty upload.")
        if len(raw) > MAX_AVATAR_BYTES:
            raise ValueError("Avatar file exceeds 5 MB limit.")

        upload_dir = Path(settings.UPLOADS_DIR) / "bots" / str(bot_id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        for existing in upload_dir.glob("avatar.*"):
            existing.unlink(missing_ok=True)

        filename = f"avatar{extension}"
        destination = upload_dir / filename
        destination.write_bytes(raw)

        avatar_url = f"/uploads/bots/{bot_id}/{filename}"
        credentials = dict(bot.credentials) if isinstance(bot.credentials, dict) else {}
        credentials["avatar_url"] = avatar_url
        bot.credentials = credentials

        await db.flush()
        await db.refresh(bot)

        logger.info("BotManagement.avatar_uploaded | bot_id={bot_id}", bot_id=bot_id)
        return BotAvatarUploadResponse(bot_id=bot_id, avatar_url=avatar_url)

    async def get_bot_profile(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
    ) -> BotAgentProfileRead:
        bot = await self._get_bot(db, bot_id)
        return BotAgentProfileRead.model_validate(bot)

    async def update_bot_prompting(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: BotPromptingUpdate,
    ) -> BotAgentProfileRead:
        bot = await self._get_bot(db, bot_id)

        if payload.prompt_instructions is not None:
            bot.prompt_instructions = payload.prompt_instructions
        if payload.llm_model_name is not None:
            bot.llm_model_name = payload.llm_model_name
        if payload.llm_temperature is not None:
            bot.llm_temperature = payload.llm_temperature

        visibility_patch: dict[str, bool] = {}
        if payload.show_username_visibility is not None:
            visibility_patch["show_username_visibility"] = payload.show_username_visibility
        if payload.show_messenger_visibility is not None:
            visibility_patch["show_messenger_visibility"] = payload.show_messenger_visibility
        if payload.show_datetime_visibility is not None:
            visibility_patch["show_datetime_visibility"] = payload.show_datetime_visibility

        if visibility_patch:
            schedule = dict(bot.schedule_config or {})
            prompting_visibility = dict(schedule.get("prompting_visibility") or {})
            prompting_visibility.update(visibility_patch)
            schedule["prompting_visibility"] = prompting_visibility
            bot.schedule_config = schedule

        await db.flush()
        await db.refresh(bot)
        await llm_response_cache.invalidate_bot_cache(bot_id)
        logger.info("BotManagement.prompting_updated | bot_id={bot_id}", bot_id=bot_id)
        return BotAgentProfileRead.model_validate(bot)

    async def optimize_bot_prompt(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: OptimizePromptRequest,
    ) -> OptimizePromptResponse:
        await self._get_bot(db, bot_id)
        optimized = await prompt_optimization_service.optimize_prompt(
            bot_id=bot_id,
            prompt_instructions=payload.prompt_instructions,
        )
        return OptimizePromptResponse(
            bot_id=bot_id,
            optimized_prompt=optimized,
        )

    async def enhance_bot_prompt(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: EnhancePromptRequest,
    ) -> EnhancePromptResponse:
        await self._get_bot(db, bot_id)
        enhanced = await prompt_optimization_service.optimize_prompt(
            bot_id=bot_id,
            prompt_instructions=payload.prompt_instructions,
        )
        return EnhancePromptResponse(
            bot_id=bot_id,
            enhanced_prompt=enhanced,
        )

    async def update_bot_llm_config(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: BotLLMConfigUpdate,
    ) -> BotAgentProfileRead:
        bot = await self._get_bot(db, bot_id)
        bot.llm_model_name = payload.llm_model_name
        bot.llm_temperature = payload.llm_temperature
        await db.flush()
        await db.refresh(bot)
        await llm_response_cache.invalidate_bot_cache(bot_id)
        logger.info(
            "BotManagement.llm_updated | bot_id={bot_id} model={model}",
            bot_id=bot_id,
            model=payload.llm_model_name,
        )
        return BotAgentProfileRead.model_validate(bot)

    async def update_bot_functions(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        payload: BotFunctionsUpdate,
    ) -> BotAgentProfileRead:
        bot = await self._get_bot(db, bot_id)
        if payload.custom_code_snippet is not None:
            bot.custom_code_snippet = payload.custom_code_snippet
        if payload.function_tools is not None:
            from app.services.bot_workspace_config import (
                get_workspace,
                set_workspace,
                validate_function_name,
                new_id,
            )

            workspace = get_workspace(bot)
            normalized: list[dict] = []
            for item in payload.function_tools:
                name = validate_function_name(str(item.get("name") or ""))
                normalized.append(
                    {
                        "id": str(item.get("id") or new_id()),
                        "name": name,
                        "description": str(item.get("description") or "").strip(),
                        "parameters": list(item.get("parameters") or []),
                        "reaction_mode": str(item.get("reaction_mode") or "llm"),
                        "reaction_text": str(item.get("reaction_text") or ""),
                        "integration": str(item.get("integration") or "none"),
                        "result_integrations": list(item.get("result_integrations") or []),
                        "result_fields": list(item.get("result_fields") or []),
                        "post_scenario": str(item.get("post_scenario") or "continue"),
                        "nested_function_id": item.get("nested_function_id") or None,
                        "disable_delayed_messages": bool(
                            item.get("disable_delayed_messages", False)
                        ),
                        "is_active": bool(item.get("is_active", True)),
                    }
                )
            workspace["functions"] = normalized
            set_workspace(bot, workspace)
        await db.flush()
        await db.refresh(bot)
        logger.info(
            "BotManagement.functions_updated | bot_id={bot_id} snippet_len={length}",
            bot_id=bot_id,
            length=len(payload.custom_code_snippet or ""),
        )
        return BotAgentProfileRead.model_validate(bot)

    async def toggle_knowledge_document_context(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        document_id: uuid.UUID,
        *,
        is_context_active: bool,
    ) -> BotKnowledgeToggleResponse:
        """Flip ``is_context_active`` and immediately clear the RAG activation cache.

        Used by ``PATCH /api/v1/bots/{bot_id}/knowledge/{doc_id}/toggle`` so Test Chat
        / live dialogs never retrieve deactivated file or URL vectors.
        """
        await self._get_bot(db, bot_id)
        result = await knowledge_base_service.set_document_context_active(
            db,
            bot_id,
            document_id,
            is_context_active=is_context_active,
        )
        # Belt-and-suspenders: service already invalidates; ensure orchestrator utils
        # expose an explicit cache clear for the enhancement layer.
        rag_activation_cache.invalidate(bot_id)
        await knowledge_base_service.invalidate_retrieval_cache(bot_id)
        await llm_response_cache.invalidate_bot_cache(bot_id)

        logger.info(
            "BotManagement.knowledge_toggled | bot_id={bot_id} document_id={document_id} active={active}",
            bot_id=bot_id,
            document_id=document_id,
            active=is_context_active,
        )
        return BotKnowledgeToggleResponse(
            bot_id=result.bot_id,
            document_id=result.document_id,
            is_context_active=result.is_context_active,
            message=result.message,
        )

    async def delete_bot(
        self,
        db: AsyncSession,
        bot_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None = None,
    ) -> dict:
        """Thin alias — cascade lives in ``bot_service.delete_bot_cascade``."""
        from app.services.bot_service import BotNotFoundError, bot_service

        bot = await self._get_bot(db, bot_id)
        org_id = organization_id or bot.organization_id
        if org_id is None:
            raise ValueError(f"Bot '{bot_id}' is not bound to an organization.")
        try:
            return await bot_service.delete_bot_cascade(db, bot_id, org_id)
        except BotNotFoundError:
            raise

    async def _get_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Bot:
        result = await db.execute(
            select(Bot).where(Bot.id == bot_id, Bot.deleted_at.is_(None))
        )
        bot = result.scalar_one_or_none()
        if bot is None:
            raise ValueError(f"Bot '{bot_id}' not found")
        return bot

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
            email="admin@mp.ai",
            hashed_password="!",
            company_name="MP.AI Production Console",
            full_name="Workspace Owner",
            role=UserRole.OWNER,
        )
        db.add(user)
        await db.flush()
        user.company_id = user.id
        await db.flush()
        return user


bot_management_service = BotManagementService()


def graph_validation_http_exception(exc: GraphValidationError):
    from fastapi import HTTPException, status

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=issues_to_http_detail(exc.issues),
    )
