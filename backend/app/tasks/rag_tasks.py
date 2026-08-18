"""Celery tasks for long-running RAG ingest jobs with DB status tracking."""

from __future__ import annotations

import asyncio
import base64
import uuid
from typing import Any

from loguru import logger

from app.core.celery_app import celery_app


async def _ingest_async(
    *,
    bot_id: str,
    document_id: str,
    filename: str,
    content_b64: str,
    content_type: str | None,
    source_type: str,
    source_url: str | None,
    crawl_depth: int,
    organization_id: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    from app.core.database import async_session_factory
    from app.services.rag.ingestion import knowledge_ingestion_service

    raw = base64.b64decode(content_b64.encode("ascii")) if content_b64 else b""
    async with async_session_factory() as db:
        return await knowledge_ingestion_service.process_document(
            db,
            document_id=uuid.UUID(document_id),
            bot_id=uuid.UUID(bot_id),
            filename=filename,
            content=raw,
            content_type=content_type,
            source_type=source_type,
            source_url=source_url,
            crawl_depth=crawl_depth,
            organization_id=organization_id,
            metadata=metadata,
        )


@celery_app.task(
    name="app.tasks.rag_tasks.ingest_document_task",
    bind=True,
    max_retries=2,
    default_retry_delay=20,
)
def ingest_document_task(
    self,
    bot_id: str,
    document_id: str,
    filename: str,
    content_b64: str = "",
    content_type: str | None = None,
    source_type: str = "file",
    source_url: str | None = None,
    crawl_depth: int = 1,
    organization_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse → embed → index; updates KnowledgeBaseDocument status in PostgreSQL."""
    logger.info(
        "RAG.ingest_task_start | bot_id={bot_id} document_id={document_id} file={file} task_id={task_id}",
        bot_id=bot_id,
        document_id=document_id,
        file=filename,
        task_id=self.request.id,
    )
    try:
        result = asyncio.run(
            _ingest_async(
                bot_id=bot_id,
                document_id=document_id,
                filename=filename,
                content_b64=content_b64,
                content_type=content_type,
                source_type=source_type,
                source_url=source_url,
                crawl_depth=crawl_depth,
                organization_id=organization_id,
                metadata=metadata,
            )
        )
        if not result.get("ok"):
            # Do not retry empty extracts / permanent parse failures.
            error = str(result.get("error") or "")
            if error in {"empty_extract", "no_chunks"}:
                return result
            raise RuntimeError(error or "ingest_failed")
        return result
    except Exception as exc:
        logger.exception(
            "RAG.ingest_task_failed | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=document_id,
            error=str(exc),
        )
        # Best-effort mark FAILED if process_document did not already.
        try:
            asyncio.run(_mark_failed(document_id, str(exc)))
        except Exception:
            pass
        if self.request.retries >= self.max_retries:
            return {"ok": False, "error": str(exc), "document_id": document_id}
        raise self.retry(exc=exc) from exc


async def _mark_failed(document_id: str, error: str) -> None:
    from app.core.database import async_session_factory
    from app.models.core_models import KnowledgeDocumentStatus
    from app.services.rag.ingestion import knowledge_ingestion_service

    async with async_session_factory() as db:
        await knowledge_ingestion_service.set_status(
            db,
            uuid.UUID(document_id),
            status=KnowledgeDocumentStatus.FAILED,
            progress=100,
            error_message=error[:4000],
        )
        await db.commit()


def enqueue_document_ingest(
    *,
    bot_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    filename: str,
    content: bytes,
    content_type: str | None = None,
    source_type: str = "file",
    source_url: str | None = None,
    crawl_depth: int = 1,
    organization_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Helper for API handlers — returns Celery task id."""
    payload_b64 = base64.b64encode(content).decode("ascii") if content else ""
    async_result = ingest_document_task.delay(
        str(bot_id),
        str(document_id),
        filename,
        payload_b64,
        content_type,
        source_type,
        source_url,
        crawl_depth,
        organization_id,
        metadata,
    )
    return str(async_result.id)
