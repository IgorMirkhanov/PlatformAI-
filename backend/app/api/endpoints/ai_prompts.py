"""AI prompt optimization endpoints (flow builder, operators)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import (
    Permission,
    assert_permission,
    can_manage_flows,
    can_manage_settings,
    get_current_user,
)
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.core_schemas import OptimizeAIPromptRequest, OptimizeAIPromptResponse
from app.services.llm.base import InsufficientCreditsForLLMError
from app.services.prompt_optimization_service import prompt_optimization_service

router = APIRouter(prefix="/ai", tags=["ai-prompts"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _require_prompt_optimizer(user: User) -> User:
    role = user.role or UserRole.OPERATOR
    if can_manage_flows(role) or can_manage_settings(role):
        return user
    try:
        assert_permission(role, Permission.BOT_PROMPTING)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: prompt optimization requires flow or prompting access.",
        ) from exc
    return user


@router.post(
    "/optimize-prompt",
    response_model=OptimizeAIPromptResponse,
    summary="Optimize a raw system prompt with AI",
)
async def optimize_prompt(
    payload: OptimizeAIPromptRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OptimizeAIPromptResponse:
    """
    Transform a raw operator prompt into a structured production system prompt.

    Uses ``gpt-4o-mini`` via the billed LLM gateway (org credit wallet preflight).
    """
    _require_prompt_optimizer(current_user)
    org_id = _org_id(current_user)

    try:
        result = await prompt_optimization_service.optimize_prompt_for_organization(
            db,
            organization_id=org_id,
            user_id=current_user.id,
            prompt_text=payload.prompt_text,
            bot_task=payload.bot_task,
        )
        await db.commit()
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid optimize payload", "issues": exc.errors()},
        ) from exc
    except InsufficientCreditsForLLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc) or "Insufficient credits for prompt optimization.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "AIPrompts.optimize_failed | org={org} user={user}",
            org=org_id,
            user=current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to optimize prompt.",
        ) from exc

    return OptimizeAIPromptResponse(
        optimized_prompt=result.optimized_prompt,
        model_name=result.model_name,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
