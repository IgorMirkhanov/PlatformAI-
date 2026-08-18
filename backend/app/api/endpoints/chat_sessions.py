"""Backward-compatible re-export of the operator chat intercept engine."""

from app.api.endpoints.chat import router

__all__ = ["router"]
