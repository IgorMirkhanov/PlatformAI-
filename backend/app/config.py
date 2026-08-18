"""Application configuration entrypoint for Celery and shared runtime settings."""

from app.core.config import Settings, settings

__all__ = ["Settings", "settings"]
