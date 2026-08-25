"""Stripe + usage billing endpoints (organization-scoped)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.admin import ensure_not_impersonated
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import SubscriptionPlanName
from app.models.users import User
from app.services.stripe_billing_service import StripeNotConfigured, stripe_billing_service
from app.services.stripe_service import stripe_service
from app.services.usage_service import usage_service

router = APIRouter(prefix="/billing", tags=["billing-stripe"])


class CheckoutRequest(BaseModel):
    plan: SubscriptionPlanName = SubscriptionPlanName.PRO
    organization_id: uuid.UUID | None = None
    price_id: str | None = Field(default=None, description="Optional Stripe Price id override")
    success_url: HttpUrl
    cancel_url: HttpUrl


class PortalRequest(BaseModel):
    return_url: HttpUrl
    organization_id: uuid.UUID | None = None


def _resolve_org_id(user: User, organization_id: uuid.UUID | None) -> uuid.UUID:
    # Never trust client-supplied org unless it matches the active workspace
    # (superadmin/support may opt into another org only via impersonation JWT).
    active = getattr(user, "company_id", None)
    if organization_id is not None and organization_id != active:
        if not (
            getattr(user, "is_superadmin", False) or getattr(user, "is_support", False)
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="organization_id does not match your active workspace.",
            )
    org_id = organization_id or active
    if org_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="organization_id required (or set active company on user)",
        )
    return org_id


@router.get("/usage")
async def get_usage(
    days: int = 30,
    organization_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    org_id = _resolve_org_id(current_user, organization_id)
    return await usage_service.summarize_period(db, organization_id=org_id, days=days)


@router.get("/stripe/status")
async def stripe_status(
    organization_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Enabled flag + organization Stripe snapshot."""
    base = {"enabled": stripe_billing_service.enabled()}
    org_id = _resolve_org_id(current_user, organization_id)
    snap = await stripe_billing_service.get_org_billing_snapshot(db, organization_id=org_id)
    return {**base, **snap}


@router.post("/stripe/checkout")
async def stripe_plan_checkout(
    payload: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(ensure_not_impersonated),
) -> dict:
    """Subscription plan Checkout (PRO / ENTERPRISE). Wallet top-up uses POST /billing/checkout."""
    org_id = _resolve_org_id(current_user, payload.organization_id)
    try:
        return await stripe_billing_service.create_checkout_session(
            db,
            organization_id=org_id,
            email=current_user.email,
            plan=payload.plan,
            price_id=payload.price_id,
            success_url=str(payload.success_url),
            cancel_url=str(payload.cancel_url),
            user_id=current_user.id,
        )
    except StripeNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/stripe/portal")
async def stripe_org_portal(
    payload: PortalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(ensure_not_impersonated),
) -> dict:
    """Org portal (POST body). Prefer GET /billing/portal for wallet card management."""
    org_id = _resolve_org_id(current_user, payload.organization_id)
    try:
        return await stripe_billing_service.create_portal_session(
            db, organization_id=org_id, return_url=str(payload.return_url)
        )
    except StripeNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/stripe/webhook")
async def stripe_webhook_alias(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict:
    """Alias of POST /billing/webhook — kept for existing Stripe dashboard configs."""
    if not stripe_signature:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing Stripe-Signature")
    payload = await request.body()
    try:
        return await stripe_service.handle_webhook(db, payload, stripe_signature)
    except StripeNotConfigured as exc:
        from app.core.metrics import record_webhook_failure

        record_webhook_failure("stripe")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        from app.core.metrics import record_webhook_failure

        record_webhook_failure("stripe")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
