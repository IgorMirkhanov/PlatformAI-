"""Bot lifecycle endpoints — cascade delete and clone."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission, get_current_user
from app.models.core_models import Bot
from app.models.users import User
from app.schemas.core_schemas import CreateBotResponse
from app.services.bot_service import BotNotFoundError, BotOrgMismatchError, bot_service

router = APIRouter(prefix="/bots", tags=["bots-lifecycle"])


def _resolve_org_id(bot: Bot, current_user: User) -> uuid.UUID:
    if bot.organization_id is not None:
        return bot.organization_id
    company_id = getattr(current_user, "company_id", None)
    if company_id is not None:
        return company_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Bot is not bound to an organization.",
    )


@router.post(
    "/{bot_id}/clone",
    response_model=CreateBotResponse,
    summary="Clone a bot (flow graph + prompt/LLM settings)",
)
async def clone_bot(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    source_bot: Bot = Depends(require_bot_access(Permission.BOT_SETTINGS)),
) -> CreateBotResponse:
    _ = source_bot
    try:
        org_id = _resolve_org_id(source_bot, current_user)
        return await bot_service.clone_bot(
            db,
            bot_id,
            org_id=org_id,
            current_user_id=current_user.id,
        )
    except BotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BotOrgMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Bots.clone_failed | bot_id={bot_id} error={error}", bot_id=bot_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clone bot.",
        ) from exc


@router.delete(
    "/{bot_id}",
    summary="Permanently delete a bot and cascade related data",
    status_code=status.HTTP_200_OK,
)
async def delete_bot(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    bot: Bot = Depends(require_bot_access(Permission.BOT_SETTINGS)),
) -> dict:
    """
    Cascading hard-delete: WhatsApp session, Chroma embeddings, KB docs,
    LLM usage logs, diagnostic logs, flows, then the bot row.
    """
    _ = current_user
    try:
        org_id = _resolve_org_id(bot, current_user)
        result = await bot_service.delete_bot_cascade(db, bot_id, org_id)
        return {
            **result,
            "message": "Bot and related data permanently deleted.",
        }
    except BotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BotOrgMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Bots.delete_failed | bot_id={bot_id} error={error}", bot_id=bot_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete bot.",
        ) from exc


# Re-export for tests / explicit imports.
__all__ = ["router", "clone_bot", "delete_bot"]
