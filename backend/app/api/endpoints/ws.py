"""Backward-compatible re-export of the operator WebSocket feed."""

from app.api.websockets.operator_ws import router

__all__ = ["router"]
