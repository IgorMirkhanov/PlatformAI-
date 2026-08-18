"""Knowledge base API — list/upload/delete + retrieval debugger.

``kb_id`` follows the existing convention: knowledge base id == bot UUID.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bot_for_workspace
from app.core.database import get_db
from app.core.rbac import Permission, assert_permission, get_current_user
from app.core.vector_db import similarity_search_detailed
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.knowledge_base_schemas import (
    KnowledgeAsyncUploadResponse,
    KnowledgeBaseDeleteResponse,
    KnowledgeBaseDocumentListResponse,
    KnowledgeTestSearchChunk,
    KnowledgeTestSearchRequest,
    KnowledgeTestSearchResponse,
)
from app.services.knowledge_base_service import knowledge_base_service
from app.services.rag.ingestion import knowledge_ingestion_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md", ".markdown", ".csv", ".json"}


def _normalize_upload_file_name(file: UploadFile) -> str:
    from pathlib import Path

    raw = (file.filename or "uploaded-document.txt").strip() or "uploaded-document.txt"
    name = Path(raw).name
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-")
    return safe or "uploaded-document.txt"


async def _assert_kb_access(db: AsyncSession, current_user: User, kb_id: uuid.UUID) -> None:
    assert_permission(current_user.role or UserRole.OPERATOR, Permission.BOT_KNOWLEDGE)
    await get_bot_for_workspace(bot_id=kb_id, db=db, current_user=current_user)


@router.get(
    "/{kb_id}/documents",
    response_model=KnowledgeBaseDocumentListResponse,
    summary="List knowledge base documents",
)
async def list_knowledge_documents(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeBaseDocumentListResponse:
    await _assert_kb_access(db, current_user, kb_id)
    try:
        return await knowledge_base_service.list_documents(db, kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Knowledge.list_error | kb_id={kb_id} error={error}", kb_id=kb_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load knowledge documents.",
        ) from exc


@router.post(
    "/{kb_id}/upload",
    response_model=KnowledgeAsyncUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue file or URL ingest (Celery)",
)
async def upload_knowledge_document(
    kb_id: uuid.UUID,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    file_name: str | None = Form(default=None),
    crawl_depth: int = Form(default=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeAsyncUploadResponse:
    await _assert_kb_access(db, current_user, kb_id)
    meta = {"uploaded_by": str(current_user.id)}
    try:
        if file is not None:
            upload_name = _normalize_upload_file_name(file)
            extension = upload_name[upload_name.rfind(".") :].lower() if "." in upload_name else ""
            if extension and extension not in _SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Supported formats: PDF, TXT, DOCX.",
                )
            raw_bytes = await file.read()
            if not raw_bytes:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Uploaded file is empty.",
                )
            result = await knowledge_ingestion_service.enqueue_file_ingest(
                db,
                kb_id,
                filename=upload_name,
                content=raw_bytes,
                content_type=file.content_type,
                metadata=meta,
            )
        elif url and url.strip():
            result = await knowledge_ingestion_service.enqueue_url_ingest(
                db,
                kb_id,
                url=url.strip(),
                file_name=file_name,
                crawl_depth=crawl_depth,
                metadata=meta,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide a file upload or a URL.",
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Knowledge.upload_error | kb_id={kb_id} error={error}", kb_id=kb_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue knowledge ingest.",
        ) from exc

    return KnowledgeAsyncUploadResponse(
        task_id=result["task_id"],
        document_id=uuid.UUID(result["document_id"]),
        bot_id=uuid.UUID(result["bot_id"]),
        kb_id=result["kb_id"],
        status="PENDING",
    )


@router.delete(
    "/{kb_id}/documents/{document_id}",
    response_model=KnowledgeBaseDeleteResponse,
    summary="Delete document row and purge Chroma vectors",
)
async def delete_knowledge_document(
    kb_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeBaseDeleteResponse:
    await _assert_kb_access(db, current_user, kb_id)
    try:
        return await knowledge_base_service.delete_document(db, kb_id, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Knowledge.delete_error | kb_id={kb_id} document_id={document_id} error={error}",
            kb_id=kb_id,
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete knowledge document.",
        ) from exc


@router.post(
    "/{kb_id}/test-search",
    response_model=KnowledgeTestSearchResponse,
    summary="Retrieval debugger — embed query and return top chunks with scores",
)
async def test_knowledge_search(
    kb_id: uuid.UUID,
    payload: KnowledgeTestSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeTestSearchResponse:
    await _assert_kb_access(db, current_user, kb_id)
    try:
        bot = await knowledge_base_service._get_bot(db, kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    org_id = str(bot.organization_id) if bot.organization_id else None
    try:
        active_ids = await knowledge_base_service.get_active_document_ids(db, kb_id)
        if not active_ids:
            return KnowledgeTestSearchResponse(
                kb_id=str(kb_id),
                query=payload.query,
                top_k=payload.top_k,
                chunks=[],
                total=0,
            )
        hits = await similarity_search_detailed(
            knowledge_base_id=str(kb_id),
            query=payload.query,
            top_k=payload.top_k,
            allowed_document_ids=active_ids,
            organization_id=org_id,
        )
    except Exception as exc:
        logger.exception(
            "Knowledge.test_search_error | kb_id={kb_id} error={error}",
            kb_id=kb_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to run retrieval test.",
        ) from exc

    chunks: list[KnowledgeTestSearchChunk] = []
    for hit in hits:
        score = float(hit.get("similarity_score") or 0.0)
        distance = round(max(0.0, 1.0 - score), 4)
        chunks.append(
            KnowledgeTestSearchChunk(
                text=hit["text"],
                similarity_score=score,
                cosine_distance=distance,
                match_percent=int(round(score * 100)),
                file_name=hit.get("file_name"),
                document_id=hit.get("document_id"),
                page_number=hit.get("page_number"),
                section=hit.get("section"),
                chunk_index=hit.get("chunk_index"),
            )
        )

    return KnowledgeTestSearchResponse(
        kb_id=str(kb_id),
        query=payload.query,
        top_k=payload.top_k,
        chunks=chunks,
        total=len(chunks),
    )
