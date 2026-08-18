"""Legacy Telegram webhook routes — prefer app.api.endpoints.webhooks."""

from app.api.endpoints.webhooks import router

__all__ = ["router"]
