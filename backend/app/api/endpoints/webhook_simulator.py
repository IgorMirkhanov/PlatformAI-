"""Legacy webhook simulator routes — prefer app.api.endpoints.webhooks."""

from app.api.endpoints.webhooks import router

__all__ = ["router"]
