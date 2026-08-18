"""Administrative system diagnostics endpoints (Cursor export engine)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import Permission, require_permission
from app.models.users import User
from app.schemas.diagnostic_schemas import DiagnosticsExportResponse
from app.services.cursor_diagnostic_exporter import cursor_diagnostic_exporter

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/diagnostics/export", response_model=DiagnosticsExportResponse)
async def export_cursor_diagnostics(
    bot_id: uuid.UUID | None = Query(
        default=None,
        description="Optional bot scope. When omitted, exports workspace-wide recent errors.",
    ),
    limit: int = Query(default=50, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> DiagnosticsExportResponse:
    """Export a Cursor-ready markdown diagnostic dump (errors + safe env metadata)."""
    _ = current_user
    try:
        return await cursor_diagnostic_exporter.export_markdown(
            db,
            bot_id=bot_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("System.diagnostics_export_failed | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export diagnostic dump.",
        ) from exc
