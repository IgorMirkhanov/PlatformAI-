"""Native CRM — deals HTTP API (OWNER/ADMIN/OPERATOR with per-deal scoping)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.crm.deps import (
    crm_actor,
    crm_org_id,
    require_crm_deal_access,
    require_crm_deal_admin,
)
from app.core.database import get_db
from app.models.crm.deal import DealStatus
from app.models.users import User
from app.schemas.crm.deals import (
    CrmDealCloseRequest,
    CrmDealCreate,
    CrmDealListResponse,
    CrmDealMoveStageRequest,
    CrmDealRead,
    CrmDealUpdate,
)
from app.schemas.crm.tags_fields import CrmTagRead
from app.services.crm.deal_service import DealServiceError, deal_service
from app.services.crm.tag_service import TagServiceError, tag_service

router = APIRouter(prefix="/crm/deals", tags=["crm-deals"])


def _http_error(exc: DealServiceError | TagServiceError) -> HTTPException:
    if exc.status_code == status.HTTP_402_PAYMENT_REQUIRED:
        return HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "crm_deals_open_limit",
                "message": exc.message,
                "billing_url": "/billing",
            },
        )
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=CrmDealListResponse, summary="List CRM deals")
async def list_deals(
    pipeline_id: uuid.UUID | None = Query(default=None),
    stage_id: uuid.UUID | None = Query(default=None),
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    contact_id: uuid.UUID | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmDealListResponse:
    return await deal_service.list_deals(
        db,
        crm_org_id(current_user),
        actor=crm_actor(current_user),
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        status=status_filter,
        contact_id=contact_id,
        account_id=account_id,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/{deal_id}", response_model=CrmDealRead, summary="Get CRM deal")
async def get_deal(
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmDealRead:
    try:
        return await deal_service.get_deal(
            db,
            crm_org_id(current_user),
            deal_id,
            actor=crm_actor(current_user),
        )
    except DealServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "",
    response_model=CrmDealRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM deal",
)
async def create_deal(
    payload: CrmDealCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmDealRead:
    try:
        actor = crm_actor(current_user)
        return await deal_service.create_deal(
            db,
            crm_org_id(current_user),
            payload,
            actor=actor,
            actor_id=actor.user_id,
        )
    except DealServiceError as exc:
        raise _http_error(exc) from exc


@router.patch("/{deal_id}", response_model=CrmDealRead, summary="Update CRM deal")
async def update_deal(
    deal_id: uuid.UUID,
    payload: CrmDealUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmDealRead:
    try:
        return await deal_service.update_deal(
            db,
            crm_org_id(current_user),
            deal_id,
            payload,
            actor=crm_actor(current_user),
        )
    except DealServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{deal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM deal",
)
async def delete_deal(
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> None:
    try:
        await deal_service.delete_deal(
            db,
            crm_org_id(current_user),
            deal_id,
            actor=crm_actor(current_user),
        )
    except DealServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{deal_id}/move-stage",
    response_model=CrmDealRead,
    summary="Move deal to another stage in the same pipeline",
)
async def move_deal_stage(
    deal_id: uuid.UUID,
    payload: CrmDealMoveStageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmDealRead:
    try:
        actor = crm_actor(current_user)
        return await deal_service.move_stage(
            db,
            crm_org_id(current_user),
            deal_id,
            payload.stage_id,
            actor=actor,
            actor_id=actor.user_id,
        )
    except DealServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{deal_id}/close",
    response_model=CrmDealRead,
    summary="Close deal as won or lost",
)
async def close_deal(
    deal_id: uuid.UUID,
    payload: CrmDealCloseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmDealRead:
    try:
        actor = crm_actor(current_user)
        return await deal_service.close_deal(
            db,
            crm_org_id(current_user),
            deal_id,
            payload,
            actor=actor,
            actor_id=actor.user_id,
        )
    except DealServiceError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{deal_id}/tags/{tag_id}",
    response_model=CrmTagRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach tag to deal",
)
async def attach_deal_tag(
    deal_id: uuid.UUID,
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> CrmTagRead:
    try:
        await deal_service.get_deal(
            db,
            crm_org_id(current_user),
            deal_id,
            actor=crm_actor(current_user),
        )
        return await tag_service.attach_tag_to_deal(
            db,
            crm_org_id(current_user),
            deal_id,
            tag_id,
            actor_id=current_user.id,
        )
    except (DealServiceError, TagServiceError) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{deal_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove tag from deal",
)
async def remove_deal_tag(
    deal_id: uuid.UUID,
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_access),
) -> None:
    try:
        await deal_service.get_deal(
            db,
            crm_org_id(current_user),
            deal_id,
            actor=crm_actor(current_user),
        )
        await tag_service.remove_tag_from_deal(
            db,
            crm_org_id(current_user),
            deal_id,
            tag_id,
            actor_id=current_user.id,
        )
    except (DealServiceError, TagServiceError) as exc:
        raise _http_error(exc) from exc
