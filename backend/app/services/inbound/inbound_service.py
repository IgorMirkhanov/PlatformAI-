"""Inbound message helpers — exception logging for Telegram / messenger pipelines.

Historical name referenced by ops runbooks. The live intake path is
``webhook_service.process_inbound_message`` + Celery workers; this module
adds traceback-aware wrappers so LLM / RAG failures are never silent.
"""

from __future__ import annotations

import traceback
import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession


async def process_inbound_with_diagnostics(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID,
    external_id: str,
    username: str,
    first_name: str,
    message_text: str,
    source: str = "telegram",
    inbound_payload: dict[str, Any] | None = None,
) -> Any:
    """Delegate to ``webhook_service`` and log full traceback on failure."""
    from app.services.webhook_service import process_inbound_message

    try:
        return await process_inbound_message(
            db=db,
            bot_id=bot_id,
            external_id=external_id,
            username=username,
            first_name=first_name,
            message_text=message_text,
            source=source,
            inbound_payload=inbound_payload,
        )
    except Exception as exc:
        logger.error(
            "InboundService.process_failed | bot_id={bot_id} source={source} "
            "external_id={external_id} error={error}\n{tb}",
            bot_id=bot_id,
            source=source,
            external_id=external_id,
            error=f"{type(exc).__name__}: {exc}",
            tb=traceback.format_exc(),
        )
        raise
