"""Backward-compatible logging entrypoint — delegates to ``logging_config``."""

from __future__ import annotations

from app.core.logging_config import InterceptHandler, scrub_api_keys, setup_logging

__all__ = ["InterceptHandler", "scrub_api_keys", "setup_logging"]
