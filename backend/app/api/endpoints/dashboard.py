import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.users import User
from app.schemas.core_schemas import DashboardStatsResponse
from app.schemas.diagnostic_schemas import DiagnosticLogListResponse
from app.services.dashboard_service import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    user_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardStatsResponse:
    """Analytics panel: dialogs, message counts, token spend, agent statuses."""
    try:
        resolved_user_id = user_id or current_user.id
        return await dashboard_service.get_dashboard_stats(db=db, user_id=resolved_user_id)
    except ValueError as exc:
        await db.rollback()
        logger.error("Dashboard.stats_value_error | error={error}", error=str(exc))
        print(f"[Dashboard.stats] ValueError: {exc}", flush=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Dashboard.stats_error | error={error}", error=str(exc))
        print(f"[Dashboard.stats] Exception: {exc}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to load dashboard statistics: {exc}",
        ) from exc


@router.get("/diagnostics", response_model=DiagnosticLogListResponse)
async def get_dashboard_diagnostics(
    user_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> DiagnosticLogListResponse:
    """Recent AI Error Vault entries for workspace owners and admins."""
    try:
        return await dashboard_service.list_diagnostic_logs(db=db, user_id=user_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Dashboard.diagnostics_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load diagnostic logs.",
        ) from exc


@router.get("/export")
async def export_dashboard_analytics(
    bot_id: uuid.UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream a CSV analytics report for filtered bot/date ranges."""
    try:
        csv_payload = await dashboard_service.build_export_csv(
            db=db,
            user_id=user_id,
            bot_id=bot_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Dashboard.export_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export dashboard analytics.",
        ) from exc

    filename = "mp-ai-analytics.csv"
    return StreamingResponse(
        iter([csv_payload]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
