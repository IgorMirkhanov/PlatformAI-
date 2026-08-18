"""Backward-compatible Sentry entrypoint — delegates to ``telemetry.init_telemetry``."""

from __future__ import annotations

from app.core.telemetry import init_telemetry as init_sentry

__all__ = ["init_sentry"]
