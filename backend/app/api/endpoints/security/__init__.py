"""Security HTTP endpoints."""

from app.api.endpoints.security.audit_logs import router as audit_logs_router

__all__ = ["audit_logs_router"]
