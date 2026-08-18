"""Native CRM — public inbound lead webhook (API-key auth, no JWT)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.crm.deps import VerifiedCrmApiKeyDep
from app.core.database import get_db
from app.core.rate_limit import limiter, rate_limit_key_crm_public
from app.schemas.crm.api_keys import InboundLeadCreate, InboundLeadResponse
from app.services.crm.inbound_lead_service import InboundLeadServiceError, inbound_lead_service

router = APIRouter(prefix="/crm/public/leads", tags=["crm-public"])


def _http_error(exc: InboundLeadServiceError) -> HTTPException:
    if exc.status_code == status.HTTP_402_PAYMENT_REQUIRED:
        return HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "crm_quota",
                "message": exc.message,
                "billing_url": "/billing",
            },
        )
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "",
    response_model=InboundLeadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest inbound lead (API key)",
)
@limiter.limit("60/minute", key_func=rate_limit_key_crm_public)
async def create_inbound_lead(
    request: Request,
    payload: InboundLeadCreate,
    verified: VerifiedCrmApiKeyDep,
    db: AsyncSession = Depends(get_db),
) -> InboundLeadResponse:
    try:
        return await inbound_lead_service.ingest(
            db,
            verified.organization_id,
            payload,
        )
    except InboundLeadServiceError as exc:
        raise _http_error(exc) from exc
