"""Admin test chat — org-billed LLM turns against the published flow graph."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission
from app.models.core_models import Bot
from app.schemas.sandbox_schemas import SandboxChatResponse, SandboxMessageRequest
from app.services.sandbox_service import sandbox_service

router = APIRouter(prefix="/bots", tags=["test-chat"])


@router.post(
    "/{bot_id}/test-chat/message",
    response_model=SandboxChatResponse,
    summary="Send a test chat message (admin panel)",
)
async def post_test_chat_message(
    bot_id: uuid.UUID,
    payload: SandboxMessageRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_MESSAGES)),
) -> SandboxChatResponse:
    """
    Execute one test-chat turn via ``SandboxService`` → ``AIOrchestrator`` → ``LLMGateway``.

    Uses the bot's system prompt, sandbox session history, and org wallet billing.
    """
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
            "TestChat.message_failed | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Test chat execution failed.",
        ) from exc
