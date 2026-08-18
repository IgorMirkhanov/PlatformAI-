"""Flow revision list / rollback."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_flow_access
from app.core.database import get_db
from app.core.flow_cache import published_flow_cache
from app.models.core_models import Bot
from app.services.flow_version_service import flow_version_service
from app.services.sandbox_service import sandbox_service

router = APIRouter(prefix="/bots", tags=["flow-versions"])


class RevisionRead(BaseModel):
    id: uuid.UUID
    version: int
    title: str
    note: str | None
    created_at: object

    model_config = {"from_attributes": True}


@router.get("/{bot_id}/flow/revisions", response_model=list[RevisionRead])
async def list_flow_revisions(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_flow_access()),
) -> list:
    return await flow_version_service.list_revisions(db, bot_id)


@router.post("/{bot_id}/flow/revisions/{version}/rollback")
async def rollback_flow_revision(
    bot_id: uuid.UUID,
    version: int,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_flow_access()),
) -> dict:
    try:
        flow = await flow_version_service.rollback(db, bot_id=bot_id, version=version)
        published_flow_cache.invalidate(bot_id)
        if flow.is_published:
            published_flow_cache.put_from_orm(
                flow_id=flow.id,
                bot_id=bot_id,
                title=flow.title,
                graph_data=flow.graph_data or {},
                is_published=True,
                updated_at=flow.updated_at,
            )
        try:
            from app.core.llm_cache import llm_response_cache

            await llm_response_cache.invalidate_bot_cache(bot_id)
        except Exception:
            pass
        sandbox_service.clear_session(bot_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {
        "bot_id": str(bot_id),
        "flow_id": str(flow.id),
        "restored_version": version,
        "title": flow.title,
    }
