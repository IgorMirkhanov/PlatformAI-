"""Billing HTTP endpoints package."""

from app.api.endpoints.billing.invites import router as invites_router

__all__ = ["invites_router", "router"]


def __getattr__(name: str):
    if name == "router":
        from app.api.endpoints.billing.subscriptions import router as subscriptions_router

        return subscriptions_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
