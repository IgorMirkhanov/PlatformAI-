"""Superadmin CRUD for dynamic LLM model registry."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superadmin
from app.core.database import get_db
from app.models.users import User
from app.schemas.llm_models import (
    LLMModelCreate,
    LLMModelListResponse,
    LLMModelRead,
    LLMModelUpdate,
)
from app.services.llm_model_service import LLMModelServiceError, llm_model_service

router = APIRouter(prefix="/llm-models", tags=["admin-llm-models"])


@router.get(
    "",
    response_model=LLMModelListResponse,
    summary="List all LLM models (including inactive)",
)
async def admin_list_llm_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> LLMModelListResponse:
    _ = current_user
    return await llm_model_service.list_models(db, active_only=False)


@router.post(
    "",
    response_model=LLMModelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new LLM model",
)
async def admin_create_llm_model(
    payload: LLMModelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> LLMModelRead:
    _ = current_user
    try:
        row = await llm_model_service.create_model(db, payload)
        await db.commit()
        return row
    except LLMModelServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.put(
    "/{model_id}",
    response_model=LLMModelRead,
    summary="Update LLM model parameters",
)
async def admin_update_llm_model(
    model_id: uuid.UUID,
    payload: LLMModelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> LLMModelRead:
    _ = current_user
    try:
        row = await llm_model_service.update_model(db, model_id, payload)
        await db.commit()
        return row
    except LLMModelServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.delete(
    "/{model_id}",
    response_model=LLMModelRead,
    summary="Deactivate an LLM model",
)
async def admin_deactivate_llm_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> LLMModelRead:
    _ = current_user
    try:
        row = await llm_model_service.deactivate_model(db, model_id)
        await db.commit()
        return row
    except LLMModelServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
