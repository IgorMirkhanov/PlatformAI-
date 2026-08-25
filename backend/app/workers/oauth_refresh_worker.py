"""Celery worker entry for OAuth refresh (re-exports the beat task)."""

from app.tasks.oauth_refresh_task import refresh_expiring_oauth_tokens

__all__ = ["refresh_expiring_oauth_tokens"]
