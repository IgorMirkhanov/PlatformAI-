"""Real-time operator intercept engine for live chat sessions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_bot_permission
from app.core.database import get_db
from app.core.rbac import Permission, get_current_user
from app.models.users import User
from app.schemas.core_schemas import (
    ClientInboxProfile,
    CreateCrmDealResponse,
    InterceptChatRequest,
    InterceptChatResponse,
)
from app.services.chat_service import (
    _get_client_with_bot,
    create_crm_deal_for_client,
    get_client_inbox_profile,
    intercept_chat_session,
    resume_chat_session,
)

router = APIRouter(prefix="/chat", tags=["operator-chat-sessions"])


async def _assert_inbox_session_access(
    db: AsyncSession,
    current_user: User,
    session_id: uuid.UUID,
    *,
    write: bool = False,
) -> None:
    client = await _get_client_with_bot(db, session_id)
    bot = client.bot
    if bot is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found.")
    permission = Permission.INBOX_READ if not write else Permission.INBOX_READ
    await assert_bot_permission(
        current_user=current_user,
        bot=bot,
        permission=permission,
        db=db,
    )


@router.post("/{session_id}/intercept", response_model=InterceptChatResponse)
async def intercept_dialog(
    session_id: uuid.UUID,
    payload: InterceptChatRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterceptChatResponse:
    await _assert_inbox_session_access(db, current_user, session_id, write=True)
    action = payload.action if payload else None
    if action is None:
        action = "intercept"
    return await intercept_chat_session(db=db, session_id=session_id, action=action)


@router.post("/{session_id}/resume", response_model=InterceptChatResponse)
async def resume_dialog(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterceptChatResponse:
    await _assert_inbox_session_access(db, current_user, session_id, write=True)
    return await resume_chat_session(db=db, session_id=session_id)


@router.get("/{session_id}/profile", response_model=ClientInboxProfile)
async def read_dialog_profile(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ClientInboxProfile:
    await _assert_inbox_session_access(db, current_user, session_id)
    return await get_client_inbox_profile(db=db, session_id=session_id)


@router.post("/{session_id}/crm/create-deal", response_model=CreateCrmDealResponse)
async def create_dialog_crm_deal(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CreateCrmDealResponse:
    await _assert_inbox_session_access(db, current_user, session_id, write=True)
    return await create_crm_deal_for_client(db=db, session_id=session_id)
