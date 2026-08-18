"""Omnichannel HTTP endpoints."""

from app.api.endpoints.omnichannel.telegram import router as telegram_router
from app.api.endpoints.omnichannel.whatsapp import router as whatsapp_router

__all__ = ["telegram_router", "whatsapp_router"]
