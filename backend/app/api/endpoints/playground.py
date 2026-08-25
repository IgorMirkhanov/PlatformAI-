"""Dry-run playground chat — generates without debiting the live token wallet."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bot_for_workspace
from app.core.database import get_db
from app.core.rbac import Permission, assert_permission, get_current_user
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.sandbox_schemas import RAGChunkTrace
from app.services.ai_orchestrator import AIOrchestrator
from app.services.execution_trace import ExecutionTraceBuilder

router = APIRouter(prefix="/playground", tags=["playground"])
_orchestrator = AIOrchestrator()


class PlaygroundChatRequest(BaseModel):
    bot_id: uuid.UUID
    message: str = Field(min_length=1, max_length=8000)
    dry_run: bool = True


class PlaygroundChatResponse(BaseModel):
    text: str
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_tokens: int = 0
    dry_run: bool = True
    wallet_blocked: bool = False
    rag_context: list[RAGChunkTrace] = Field(default_factory=list)


@router.post("/chat", response_model=PlaygroundChatResponse)
async def playground_chat(
    payload: PlaygroundChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlaygroundChatResponse:
    assert_permission(current_user.role or UserRole.OPERATOR, Permission.BOT_MESSAGES)
    bot = await get_bot_for_workspace(
        bot_id=payload.bot_id, db=db, current_user=current_user
    )

    node_data = {
        "prompt_context": bot.prompt_instructions or "You are a helpful assistant.",
        "llm_model_name": bot.llm_model_name,
        "temperature": bot.llm_temperature,
        "knowledge_base_id": bot.rag_collection_id,
    }
    trace = ExecutionTraceBuilder(simulation=True)
    try:
        text, metrics = await _orchestrator.generate_ai_response_with_trace(
            current_node_data=node_data,
            incoming_message=payload.message,
            db_session=db,
            bot_id=bot.id,
            channel="playground",
            dry_run=bool(payload.dry_run),
            trace=trace,
            model_name=bot.llm_model_name,
            temperature=bot.llm_temperature,
            global_prompt=bot.prompt_instructions,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Playground generation failed.",
        ) from exc

    fallback = AIOrchestrator.FUNDS_FALLBACK_MESSAGE
    custom = (getattr(bot, "low_balance_message", None) or "").strip()
    blocked = text.strip() in {fallback, custom} if custom else text.strip() == fallback
    rag = []
    try:
        schema = trace.to_model()
        rag = list(getattr(schema, "rag_context", None) or [])
    except Exception:
        rag = []
    return PlaygroundChatResponse(
        text=text,
        model_name=metrics.model_name,
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        total_tokens=metrics.total_tokens,
        estimated_cost_tokens=metrics.total_tokens,
        dry_run=bool(payload.dry_run),
        wallet_blocked=blocked,
        rag_context=rag,
    )
