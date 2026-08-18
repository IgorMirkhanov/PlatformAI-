"""Native CRM — pipeline / stage HTTP API (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_roles
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.crm.pipelines import (
    CrmPipelineCreate,
    CrmPipelineRead,
    CrmPipelineUpdate,
    CrmStageCreate,
    CrmStageRead,
    CrmStageReorderRequest,
    CrmStageUpdate,
)
from app.services.crm.pipeline_service import PipelineServiceError, pipeline_service

router = APIRouter(prefix="/crm/pipelines", tags=["crm-pipelines"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _http_error(exc: PipelineServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "",
    response_model=list[CrmPipelineRead],
    summary="List CRM pipelines with stages",
)
async def list_pipelines(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> list[CrmPipelineRead]:
    return await pipeline_service.list_pipelines(db, _org_id(current_user))


@router.post(
    "",
    response_model=CrmPipelineRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a CRM pipeline",
)
async def create_pipeline(
    payload: CrmPipelineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmPipelineRead:
    return await pipeline_service.create_pipeline(db, _org_id(current_user), payload)


@router.patch(
    "/{pipeline_id}",
    response_model=CrmPipelineRead,
    summary="Update a CRM pipeline",
)
async def update_pipeline(
    pipeline_id: uuid.UUID,
    payload: CrmPipelineUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmPipelineRead:
    try:
        return await pipeline_service.update_pipeline(
            db, _org_id(current_user), pipeline_id, payload
        )
    except PipelineServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{pipeline_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a CRM pipeline",
)
async def delete_pipeline(
    pipeline_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await pipeline_service.delete_pipeline(db, _org_id(current_user), pipeline_id)
    except PipelineServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{pipeline_id}/stages",
    response_model=CrmStageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a stage to a pipeline",
)
async def create_stage(
    pipeline_id: uuid.UUID,
    payload: CrmStageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmStageRead:
    try:
        return await pipeline_service.create_stage(
            db, _org_id(current_user), pipeline_id, payload
        )
    except PipelineServiceError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{pipeline_id}/stages/{stage_id}",
    response_model=CrmStageRead,
    summary="Update a pipeline stage",
)
async def update_stage(
    pipeline_id: uuid.UUID,
    stage_id: uuid.UUID,
    payload: CrmStageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> CrmStageRead:
    try:
        return await pipeline_service.update_stage(
            db, _org_id(current_user), pipeline_id, stage_id, payload
        )
    except PipelineServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{pipeline_id}/stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a pipeline stage",
)
async def delete_stage(
    pipeline_id: uuid.UUID,
    stage_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await pipeline_service.delete_stage(
            db, _org_id(current_user), pipeline_id, stage_id
        )
    except PipelineServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{pipeline_id}/stages/reorder",
    response_model=list[CrmStageRead],
    summary="Reorder stages within a pipeline",
)
async def reorder_stages(
    pipeline_id: uuid.UUID,
    payload: CrmStageReorderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> list[CrmStageRead]:
    positions = [(item.id, item.position) for item in payload.stages]
    try:
        return await pipeline_service.reorder_stages(
            db, _org_id(current_user), pipeline_id, positions
        )
    except PipelineServiceError as exc:
        raise _http_error(exc) from exc
