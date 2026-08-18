"""Native CRM — outbound webhook subscription endpoints (OWNER/ADMIN)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.crm.deps import crm_org_id, require_crm_deal_admin
from app.core.database import get_db
from app.models.users import User
from app.schemas.crm.webhooks import (
    CrmWebhookSubscriptionCreate,
    CrmWebhookSubscriptionCreated,
    CrmWebhookSubscriptionListResponse,
    CrmWebhookSubscriptionRead,
    CrmWebhookSubscriptionUpdate,
)
from app.services.crm.webhook_subscription_service import (
    WebhookSubscriptionServiceError,
    webhook_subscription_service,
)

router = APIRouter(prefix="/crm/webhooks", tags=["crm-webhooks"])


def _http_error(exc: WebhookSubscriptionServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "",
    response_model=CrmWebhookSubscriptionListResponse,
    summary="List CRM webhook subscriptions",
)
async def list_webhook_subscriptions(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmWebhookSubscriptionListResponse:
    return await webhook_subscription_service.list_subscriptions(
        db,
        crm_org_id(current_user),
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=CrmWebhookSubscriptionCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create CRM webhook subscription",
)
async def create_webhook_subscription(
    payload: CrmWebhookSubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmWebhookSubscriptionCreated:
    try:
        return await webhook_subscription_service.create_subscription(
            db,
            crm_org_id(current_user),
            payload,
        )
    except WebhookSubscriptionServiceError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{subscription_id}",
    response_model=CrmWebhookSubscriptionRead,
    summary="Get CRM webhook subscription",
)
async def get_webhook_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmWebhookSubscriptionRead:
    try:
        return await webhook_subscription_service.get_subscription(
            db,
            crm_org_id(current_user),
            subscription_id,
        )
    except WebhookSubscriptionServiceError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{subscription_id}",
    response_model=CrmWebhookSubscriptionRead,
    summary="Update CRM webhook subscription",
)
async def update_webhook_subscription(
    subscription_id: uuid.UUID,
    payload: CrmWebhookSubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmWebhookSubscriptionRead:
    try:
        return await webhook_subscription_service.update_subscription(
            db,
            crm_org_id(current_user),
            subscription_id,
            payload,
        )
    except WebhookSubscriptionServiceError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CRM webhook subscription",
)
async def delete_webhook_subscription(
    subscription_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> None:
    try:
        await webhook_subscription_service.delete_subscription(
            db,
            crm_org_id(current_user),
            subscription_id,
        )
    except WebhookSubscriptionServiceError as exc:
        raise _http_error(exc) from exc
