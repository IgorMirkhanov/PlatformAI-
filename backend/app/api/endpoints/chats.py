import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_bot_permission, require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission, get_current_user
from app.models.core_models import Bot
from app.models.users import User
from app.schemas.core_schemas import (
    ActiveChatsResponse,
    ChatMessageRead,
    ManualMessageRequest,
    ToggleOperatorRequest,
    ToggleOperatorResponse,
)
from app.schemas.sandbox_schemas import SandboxChatResponse, SandboxMessageRequest
from app.services.chat_service import (
    _get_client_with_bot,
    get_active_chats,
    get_client_messages,
    send_manual_operator_message,
    toggle_operator_pause,
)
from app.services.sandbox_service import sandbox_service

router = APIRouter(prefix="/chats", tags=["operator-chats"])


async def _assert_client_inbox_access(
    db: AsyncSession,
    current_user: User,
    client_id: uuid.UUID,
) -> None:
    client = await _get_client_with_bot(db, client_id)
    bot = client.bot
    if bot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found.")
    await assert_bot_permission(
        current_user=current_user,
        bot=bot,
        permission=Permission.INBOX_READ,
        db=db,
    )


@router.post(
    "/{bot_id}/sandbox/message",
    response_model=SandboxChatResponse,
    summary="Live Sandbox turn (alias of /sandbox/{bot_id}/message)",
    tags=["sandbox"],
)
async def post_chat_sandbox_message(
    bot_id: uuid.UUID,
    payload: SandboxMessageRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_MESSAGES)),
) -> SandboxChatResponse:
    """Compatibility path used by the Flow Builder Live Sandbox panel."""
    try:
        return await sandbox_service.process_message(
            db=db,
            bot_id=bot_id,
            message_text=payload.text,
            session_id=payload.session_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "ChatsSandbox.message_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sandbox flow execution failed.",
        ) from exc


@router.get("/operators/context")
async def get_operator_context(
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Return the authenticated operator identity for inbox WebSocket sessions."""
    company = getattr(current_user, "company_id", None)
    return {
        "operator_id": str(current_user.id),
        "company_id": str(company) if company else str(current_user.id),
    }


@router.get("/active", response_model=ActiveChatsResponse)
async def list_active_chats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActiveChatsResponse:
    org_id = getattr(current_user, "company_id", None)
    if org_id is None and not (
        getattr(current_user, "is_superadmin", False)
        or getattr(current_user, "is_support", False)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization required.",
        )
    include_all = bool(
        getattr(current_user, "is_superadmin", False)
        or getattr(current_user, "is_support", False)
    )
    return await get_active_chats(
        db,
        organization_id=None if include_all else org_id,
        include_all=include_all,
    )


@router.get("/{client_id}/messages", response_model=list[ChatMessageRead])
async def list_client_messages(
    client_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChatMessageRead]:
    await _assert_client_inbox_access(db, current_user, client_id)
    return await get_client_messages(db, client_id)


@router.post("/{client_id}/send-manual", response_model=ChatMessageRead)
async def send_manual_message(
    client_id: uuid.UUID,
    payload: ManualMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatMessageRead:
    await _assert_client_inbox_access(db, current_user, client_id)
    return await send_manual_operator_message(
        db=db,
        client_id=client_id,
        message_text=payload.message_text,
    )


@router.post("/{client_id}/toggle-operator", response_model=ToggleOperatorResponse)
async def toggle_operator_control(
    client_id: uuid.UUID,
    payload: ToggleOperatorRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ToggleOperatorResponse:
    await _assert_client_inbox_access(db, current_user, client_id)
    paused = payload.paused if payload else None
    return await toggle_operator_pause(db=db, client_id=client_id, paused=paused)
