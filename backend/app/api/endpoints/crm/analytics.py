"""Native CRM — analytics endpoints (OWNER/ADMIN)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.crm.deps import crm_org_id, require_crm_deal_admin
from app.core.database import get_db
from app.models.users import User
from app.schemas.crm.analytics import (
    CrmForecastResponse,
    CrmFunnelResponse,
    CrmPerformanceResponse,
)
from app.services.crm.crm_analytics_service import (
    CrmAnalyticsServiceError,
    crm_analytics_service,
)

router = APIRouter(prefix="/crm/analytics", tags=["crm-analytics"])


def _http_error(exc: CrmAnalyticsServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get(
    "/funnel",
    response_model=CrmFunnelResponse,
    summary="Pipeline conversion funnel",
)
async def get_funnel(
    pipeline_id: uuid.UUID = Query(...),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmFunnelResponse:
    try:
        return await crm_analytics_service.get_pipeline_funnel(
            db,
            crm_org_id(current_user),
            pipeline_id,
            start_date=start_date,
            end_date=end_date,
        )
    except CrmAnalyticsServiceError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/performance",
    response_model=CrmPerformanceResponse,
    summary="Manager win/loss performance",
)
async def get_performance(
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmPerformanceResponse:
    return await crm_analytics_service.get_manager_performance(
        db,
        crm_org_id(current_user),
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/forecast",
    response_model=CrmForecastResponse,
    summary="Open-pipeline revenue forecast",
)
async def get_forecast(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_crm_deal_admin),
) -> CrmForecastResponse:
    return await crm_analytics_service.get_revenue_forecast(
        db,
        crm_org_id(current_user),
    )
