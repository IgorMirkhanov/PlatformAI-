import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access, require_credential_access, require_flow_access
from app.core.database import get_db
from app.core.rbac import Permission, get_current_user, require_permission
from app.models.core_models import Bot
from app.models.users import User
from app.schemas.core_schemas import (
    BotAgentProfileRead,
    BotAvatarUploadResponse,
    BotChannelsResponse,
    BotFlowResponse,
    BotFunctionsUpdate,
    BotLLMConfigUpdate,
    BotPromptingUpdate,
    BotSettingsUpdate,
    ChannelIntegrationType,
    EnhancePromptRequest,
    EnhancePromptResponse,
    OptimizePromptRequest,
    OptimizePromptResponse,
    CreateBotRequest,
    CreateBotResponse,
    PublishBotFlowRequest,
    PublishBotFlowResponse,
    SaveBotFlowRequest,
    SetupChannelRequest,
    SetupChannelResponse,
    TelegramSetupRequest,
    TelegramSetupResponse,
)
from app.schemas.graph_validation import GraphValidationError
from app.services.bot_management_service import (
    bot_management_service,
    graph_validation_http_exception,
)

router = APIRouter(prefix="/bots", tags=["bot-management"])


@router.post(
    "",
    response_model=CreateBotResponse,
    summary="Create a new bot instance with optional use-case template seeding",
)
async def create_bot_root(
    payload: CreateBotRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BOT_SETTINGS)),
) -> CreateBotResponse:
    return await create_bot(payload=payload, db=db, current_user=current_user)


@router.post(
    "/create",
    response_model=CreateBotResponse,
    summary="Register a new bot instance for a platform user",
    include_in_schema=False,
)
async def create_bot(
    payload: CreateBotRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BOT_SETTINGS)),
) -> CreateBotResponse:
    try:
        if not payload.name or not payload.name.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot name is required.",
            )
        # Always bind the bot to the authenticated workspace owner context.
        bound = payload.model_copy(update={"user_id": current_user.id})
        return await bot_management_service.create_bot(
            db=db,
            payload=bound,
            current_user=current_user,
        )
    except HTTPException:
        raise
    except ValidationError as exc:
        await db.rollback()
        logger.error("BotManagement.create_validation | error={error}", error=str(exc))
        print(f"[BotManagement.create] ValidationError: {exc}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid create-bot payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        await db.rollback()
        logger.error("BotManagement.create_value_error | error={error}", error=str(exc))
        print(f"[BotManagement.create] ValueError: {exc}", flush=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("BotManagement.create_error | error={error}", error=str(exc))
        print(f"[BotManagement.create] Exception: {exc}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create bot instance: {exc}",
        ) from exc


@router.get(
    "/{bot_id}/flow",
    response_model=BotFlowResponse,
    summary="Load the latest published or saved flow graph for canvas restoration",
)
async def get_bot_flow(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_flow_access()),
) -> BotFlowResponse:
    try:
        return await bot_management_service.get_bot_flow(db=db, bot_id=bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.get_flow_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load bot flow.",
        ) from exc


@router.post(
    "/{bot_id}/flow",
    response_model=PublishBotFlowResponse,
    summary="Serialize and save the current canvas graph (draft-friendly)",
)
async def save_bot_flow(
    bot_id: uuid.UUID,
    payload: SaveBotFlowRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_flow_access()),
) -> PublishBotFlowResponse:
    """Persist Zustand-exported nodes/edges to ``bot_flows.graph_data``."""
    try:
        return await bot_management_service.save_bot_flow(
            db=db,
            bot_id=bot_id,
            payload=payload,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=message,
        ) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.save_flow_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save bot flow.",
        ) from exc


@router.post(
    "/{bot_id}/publish",
    response_model=PublishBotFlowResponse,
    summary="Validate and publish a bot flow graph from the Flow Builder",
)
async def publish_bot_flow(
    bot_id: uuid.UUID,
    payload: PublishBotFlowRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_flow_access()),
) -> PublishBotFlowResponse:
    """Compile the canvas graph (incl. Condition / API nested configs) into PostgreSQL.

    On success the in-memory published-flow cache for ``bot_id`` is invalidated so
    the sandbox and webhook execution engines pick up the fresh logic immediately.
    """
    try:
        return await bot_management_service.publish_bot_flow(
            db=db,
            bot_id=bot_id,
            payload=payload,
        )
    except GraphValidationError as exc:
        raise graph_validation_http_exception(exc) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid publish payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        message = str(exc)
        # Distinguish missing bots from malformed graph payloads.
        if "not found" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=message,
        ) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.publish_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish bot flow.",
        ) from exc


@router.get(
    "/{bot_id}/channel-integrations",
    response_model=BotChannelsResponse,
    summary="List legacy omnichannel integration statuses (JSON credentials)",
    deprecated=True,
)
async def get_bot_channel_integrations(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_credential_access()),
) -> BotChannelsResponse:
    try:
        return await bot_management_service.get_bot_channels(db=db, bot_id=bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.channels_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load channel statuses.",
        ) from exc


async def _configure_channel(
    bot_id: uuid.UUID,
    payload: SetupChannelRequest,
    db: AsyncSession,
) -> SetupChannelResponse:
    try:
        return await bot_management_service.setup_channel(
            db=db,
            bot_id=bot_id,
            payload=payload,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid channel setup payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.setup_channel_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to configure channel credentials.",
        ) from exc


@router.post(
    "/{bot_id}/setup-channel",
    response_model=SetupChannelResponse,
    summary="Configure Telegram or WhatsApp credentials and register webhooks",
)
async def setup_channel(
    bot_id: uuid.UUID,
    payload: SetupChannelRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_credential_access()),
) -> SetupChannelResponse:
    return await _configure_channel(bot_id=bot_id, payload=payload, db=db)


@router.patch(
    "/{bot_id}/setup-channel",
    response_model=SetupChannelResponse,
    summary="Update omnichannel credentials and webhook bindings",
)
async def patch_setup_channel(
    bot_id: uuid.UUID,
    payload: SetupChannelRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_credential_access()),
) -> SetupChannelResponse:
    return await _configure_channel(bot_id=bot_id, payload=payload, db=db)


@router.patch(
    "/{bot_id}/channels/{channel_type}",
    response_model=SetupChannelResponse,
    summary="Configure a single omnichannel integration stream",
)
async def patch_bot_channel(
    bot_id: uuid.UUID,
    channel_type: ChannelIntegrationType,
    payload: SetupChannelRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_credential_access()),
) -> SetupChannelResponse:
    merged = payload.model_copy(update={"channel_type": channel_type})
    return await _configure_channel(bot_id=bot_id, payload=merged, db=db)


@router.get(
    "/{bot_id}/profile",
    response_model=BotAgentProfileRead,
    summary="Load full agent profile for the settings workspace",
)
async def get_bot_profile(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access()),
) -> BotAgentProfileRead:
    try:
        return await bot_management_service.get_bot_profile(db=db, bot_id=bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.profile_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load bot profile.",
        ) from exc


@router.patch(
    "/{bot_id}/settings",
    response_model=BotAgentProfileRead,
    summary="Update agent operational settings (status, schedule, messaging)",
)
async def update_bot_settings(
    bot_id: uuid.UUID,
    payload: BotSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_SETTINGS)),
) -> BotAgentProfileRead:
    try:
        return await bot_management_service.update_bot_settings(db=db, bot_id=bot_id, payload=payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid settings payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.settings_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update bot settings.",
        ) from exc


@router.post(
    "/{bot_id}/avatar",
    response_model=BotAvatarUploadResponse,
    summary="Upload agent avatar image",
)
async def upload_bot_avatar(
    bot_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_SETTINGS)),
) -> BotAvatarUploadResponse:
    try:
        return await bot_management_service.upload_bot_avatar(db=db, bot_id=bot_id, file=file)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.avatar_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload avatar.",
        ) from exc


@router.patch(
    "/{bot_id}/prompting",
    response_model=BotAgentProfileRead,
    summary="Update system prompt instructions for the agent",
)
async def update_bot_prompting(
    bot_id: uuid.UUID,
    payload: BotPromptingUpdate,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_PROMPTING)),
) -> BotAgentProfileRead:
    try:
        return await bot_management_service.update_bot_prompting(db=db, bot_id=bot_id, payload=payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid prompting payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.prompting_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update bot prompting.",
        ) from exc


@router.post(
    "/{bot_id}/prompting/optimize",
    response_model=OptimizePromptResponse,
    summary="Optimize system prompt instructions via AI orchestration",
)
async def optimize_bot_prompt(
    bot_id: uuid.UUID,
    payload: OptimizePromptRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_PROMPTING)),
) -> OptimizePromptResponse:
    try:
        return await bot_management_service.optimize_bot_prompt(
            db=db,
            bot_id=bot_id,
            payload=payload,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid optimize payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.optimize_prompt_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to optimize bot prompt.",
        ) from exc


@router.post(
    "/{bot_id}/prompting/enhance",
    response_model=EnhancePromptResponse,
    summary="Enhance system prompt via internal AI orchestration template",
)
async def enhance_bot_prompt(
    bot_id: uuid.UUID,
    payload: EnhancePromptRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_PROMPTING)),
) -> EnhancePromptResponse:
    try:
        return await bot_management_service.enhance_bot_prompt(
            db=db,
            bot_id=bot_id,
            payload=payload,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid enhance payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.enhance_prompt_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enhance bot prompt.",
        ) from exc


@router.patch(
    "/{bot_id}/llm-config",
    response_model=BotAgentProfileRead,
    summary="Update LLM model and temperature configuration",
)
async def update_bot_llm_config(
    bot_id: uuid.UUID,
    payload: BotLLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_LLM)),
) -> BotAgentProfileRead:
    try:
        return await bot_management_service.update_bot_llm_config(db=db, bot_id=bot_id, payload=payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid LLM config payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.llm_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update LLM configuration.",
        ) from exc


@router.patch(
    "/{bot_id}/functions",
    response_model=BotAgentProfileRead,
    summary="Save custom code snippet for function node execution",
)
async def update_bot_functions(
    bot_id: uuid.UUID,
    payload: BotFunctionsUpdate,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_FUNCTIONS)),
) -> BotAgentProfileRead:
    try:
        return await bot_management_service.update_bot_functions(db=db, bot_id=bot_id, payload=payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid functions payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotManagement.functions_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update custom functions.",
        ) from exc


@router.post(
    "/setup-telegram",
    response_model=TelegramSetupResponse,
    summary="Legacy one-shot Telegram bot registration (create + setup-channel)",
)
async def setup_telegram_bot(
    payload: TelegramSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BOT_CHANNELS)),
) -> TelegramSetupResponse:
    try:
        # Force ownership to the authenticated workspace user (ignore payload.user_id).
        bound = payload.model_copy(update={"user_id": current_user.id})
        return await bot_management_service.setup_telegram_legacy(
            db=db,
            payload=bound,
            current_user=current_user,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("BotManagement.setup_telegram_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to connect to Telegram API.",
        ) from exc
