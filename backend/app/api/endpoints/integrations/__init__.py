"""Integrations HTTP endpoints."""

from app.api.endpoints.integrations.db_connections import router as db_connections_router

__all__ = ["db_connections_router"]
