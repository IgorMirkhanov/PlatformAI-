"""LLM Gateway Knowledge Base / RAG HTTP API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import can_manage_flows, can_manage_settings, get_current_user
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.llm.rag import (
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseOut,
    KnowledgeDocumentIngestRequest,
    KnowledgeDocumentIngestResponse,
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.services.llm.rag_service import RAGServiceError, rag_service

router = APIRouter(prefix="/llm/knowledge", tags=["llm-knowledge"])


def _org_id(user: User) -> uuid.UUID:
    org_id = getattr(user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    return uuid.UUID(str(org_id))


def _require_kb_manager(user: User) -> User:
    role = user.role or UserRole.OPERATOR
    if can_manage_flows(role) or can_manage_settings(role):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied: manage flows or settings required.",
    )


def _http_error(exc: RAGServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "/bases",
    response_model=KnowledgeBaseOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create LLM knowledge base",
)
async def create_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeBaseOut:
    _require_kb_manager(current_user)
    try:
        base = await rag_service.create_knowledge_base(
            db, _org_id(current_user), name=payload.name
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return KnowledgeBaseOut.model_validate(base)


@router.get(
    "/bases",
    response_model=KnowledgeBaseListResponse,
    summary="List organization LLM knowledge bases",
)
async def list_bases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeBaseListResponse:
    _require_kb_manager(current_user)
    items = await rag_service.list_knowledge_bases(db, _org_id(current_user))
    return KnowledgeBaseListResponse(
        items=[KnowledgeBaseOut.model_validate(i) for i in items],
        total=len(items),
    )


@router.post(
    "/bases/{base_id}/documents",
    response_model=KnowledgeDocumentIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest text document (chunk + embed)",
)
async def ingest_document(
    base_id: uuid.UUID,
    payload: KnowledgeDocumentIngestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeDocumentIngestResponse:
    _require_kb_manager(current_user)
    try:
        result = await rag_service.ingest_document(
            db,
            _org_id(current_user),
            base_id,
            file_name=payload.file_name,
            text=payload.text,
            metadata=payload.metadata,
            chunk_size=payload.chunk_size,
            overlap=payload.overlap,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return KnowledgeDocumentIngestResponse(**result)


@router.post(
    "/bases/{base_id}/search",
    response_model=KnowledgeSearchResponse,
    summary="Semantic similarity search",
)
async def search_base(
    base_id: uuid.UUID,
    payload: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeSearchResponse:
    _require_kb_manager(current_user)
    try:
        hits = await rag_service.similarity_search(
            db,
            _org_id(current_user),
            base_id,
            payload.query,
            top_k=payload.top_k,
        )
    except RAGServiceError as exc:
        raise _http_error(exc) from exc
    return KnowledgeSearchResponse(
        knowledge_base_id=base_id,
        query=payload.query,
        hits=[KnowledgeSearchHit(**h) for h in hits],
    )
