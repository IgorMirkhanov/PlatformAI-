"""Public LLM model catalog and connection test endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.users import User
from app.schemas.llm_models import (
    LLMModelListResponse,
    LLMModelTestConnectionRequest,
    LLMModelTestConnectionResponse,
)
from app.services.llm_model_service import LLMModelServiceError, llm_model_service

router = APIRouter(prefix="/llm-models", tags=["llm-models"])


def _org_id(user: User) -> uuid.UUID | None:
    raw = getattr(user, "company_id", None)
    if raw is None:
        return None
    return uuid.UUID(str(raw))


@router.get(
    "",
    response_model=LLMModelListResponse,
    summary="List active LLM models available in the platform",
)
async def list_llm_models(
    provider: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMModelListResponse:
    """
    Tenant catalog. Regular users always see active models only — ``active_only=false``
    is reserved for platform staff (superadmin / support).
    """
    from app.api.dependencies.admin import PlatformRole, platform_role_of

    role = platform_role_of(current_user)
    if role == PlatformRole.USER:
        active_only = True
    return await llm_model_service.list_models(
        db,
        provider=provider,
        active_only=active_only,
    )


@router.post(
    "/test-connection",
    response_model=LLMModelTestConnectionResponse,
    summary="Test connectivity to an LLM model / custom endpoint",
)
async def test_llm_model_connection(
    payload: LLMModelTestConnectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMModelTestConnectionResponse:
    try:
        return await llm_model_service.test_connection(
            db,
            payload,
            organization_id=_org_id(current_user),
        )
    except LLMModelServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
