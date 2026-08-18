"""LLM Prompt Management HTTP API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import can_manage_flows, can_manage_settings, get_current_user
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.llm.prompts import (
    PromptRenderRequest,
    PromptRenderResponse,
    PromptTemplateCreate,
    PromptTemplateListResponse,
    PromptTemplateOut,
    PromptTemplateUpdate,
)
from app.services.llm.prompt_service import (
    PromptServiceError,
    prompt_template_service,
)

router = APIRouter(prefix="/llm/prompts", tags=["llm-prompts"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _require_prompt_manager(user: User) -> User:
    role = user.role or UserRole.OPERATOR
    if can_manage_flows(role) or can_manage_settings(role):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied: manage flows or settings required.",
    )


def _http_error(exc: PromptServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "",
    response_model=PromptTemplateListResponse,
    summary="List organization prompt templates",
)
async def list_prompts(
    include_global: bool = Query(True),
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PromptTemplateListResponse:
    _require_prompt_manager(current_user)
    items = await prompt_template_service.list_templates(
        db,
        _org_id(current_user),
        include_global=include_global,
        active_only=active_only,
    )
    return PromptTemplateListResponse(
        items=[PromptTemplateOut.model_validate(i) for i in items],
        total=len(items),
    )


@router.post(
    "",
    response_model=PromptTemplateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create prompt template",
)
async def create_prompt(
    payload: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PromptTemplateOut:
    _require_prompt_manager(current_user)
    try:
        template = await prompt_template_service.create(
            db,
            _org_id(current_user),
            name=payload.name,
            content=payload.content,
            description=payload.description,
            created_by_id=current_user.id,
        )
    except PromptServiceError as exc:
        raise _http_error(exc) from exc
    return PromptTemplateOut.model_validate(template)


@router.post(
    "/render",
    response_model=PromptRenderResponse,
    summary="Render a prompt template with context",
)
async def render_prompt(
    payload: PromptRenderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PromptRenderResponse:
    _require_prompt_manager(current_user)
    if payload.template_id is None and not payload.name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either template_id or name is required.",
        )
    try:
        result = await prompt_template_service.render_template(
            db,
            _org_id(current_user),
            payload.context,
            template_id=payload.template_id,
            name=payload.name,
        )
    except PromptServiceError as exc:
        raise _http_error(exc) from exc
    return PromptRenderResponse(**result)


@router.get(
    "/{template_id}",
    response_model=PromptTemplateOut,
    summary="Get prompt template",
)
async def get_prompt(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PromptTemplateOut:
    _require_prompt_manager(current_user)
    try:
        template = await prompt_template_service.get_by_id(
            db, template_id, _org_id(current_user)
        )
    except PromptServiceError as exc:
        raise _http_error(exc) from exc
    return PromptTemplateOut.model_validate(template)


@router.put(
    "/{template_id}",
    response_model=PromptTemplateOut,
    summary="Update prompt template (increments version)",
)
async def update_prompt(
    template_id: uuid.UUID,
    payload: PromptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PromptTemplateOut:
    _require_prompt_manager(current_user)
    try:
        template = await prompt_template_service.update(
            db,
            template_id,
            _org_id(current_user),
            name=payload.name,
            content=payload.content,
            description=payload.description,
            is_active=payload.is_active,
        )
    except PromptServiceError as exc:
        raise _http_error(exc) from exc
    return PromptTemplateOut.model_validate(template)


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate prompt template",
)
async def delete_prompt(
    template_id: uuid.UUID,
    hard: bool = Query(False, description="Permanently delete instead of deactivate"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _require_prompt_manager(current_user)
    try:
        await prompt_template_service.delete(
            db, template_id, _org_id(current_user), hard=hard
        )
    except PromptServiceError as exc:
        raise _http_error(exc) from exc
