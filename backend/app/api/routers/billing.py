"""Billing router re-export (SaaS layout alias)."""

from app.api.endpoints.billing.subscriptions import router as billing_router
from app.api.endpoints.billing_stripe import router as billing_stripe_router

__all__ = ["billing_router", "billing_stripe_router"]
