import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bot_for_workspace, require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission, assert_permission, get_current_user
from app.models.core_models import Bot, UserRole
from app.models.users import User
from app.schemas.knowledge_base_schemas import (
    KnowledgeBaseDeleteResponse,
    KnowledgeBaseDocumentContextResponse,
    KnowledgeBaseDocumentContextUpdate,
    KnowledgeBaseDocumentListResponse,
    KnowledgeBaseUploadRequest,
    KnowledgeBaseUploadResponse,
)
from app.services.knowledge_base_service import knowledge_base_service

router = APIRouter(prefix="/knowledge-base", tags=["knowledge-base"])

_TEXT_FILE_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json"}


async def _decode_upload_bytes(raw_bytes: bytes) -> str:
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )

    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Unable to decode uploaded file as text.",
    )


def _normalize_upload_file_name(file: UploadFile) -> str:
    from pathlib import Path

    raw = (file.filename or "uploaded-document.txt").strip() or "uploaded-document.txt"
    name = Path(raw).name
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-")
    return safe or "uploaded-document.txt"


@router.get(
    "/{bot_id}/documents",
    response_model=KnowledgeBaseDocumentListResponse,
    summary="List indexed knowledge base documents for a bot",
)
async def list_knowledge_base_documents(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> KnowledgeBaseDocumentListResponse:
    try:
        return await knowledge_base_service.list_documents(db, bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "KnowledgeBase.list_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load knowledge base documents.",
        ) from exc


@router.patch(
    "/{bot_id}/documents/{document_id}/context",
    response_model=KnowledgeBaseDocumentContextResponse,
    summary="Associate or disassociate a document with the bot RAG context pool",
)
async def update_knowledge_document_context(
    bot_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: KnowledgeBaseDocumentContextUpdate,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> KnowledgeBaseDocumentContextResponse:
    try:
        return await knowledge_base_service.set_document_context_active(
            db,
            bot_id,
            document_id,
            is_context_active=payload.is_context_active,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception as exc:
        logger.exception(
            "KnowledgeBase.context_error | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update document context association.",
        ) from exc


@router.delete(
    "/{bot_id}/documents/{document_id}",
    response_model=KnowledgeBaseDeleteResponse,
    summary="Delete a knowledge base document and its vector chunks",
)
async def delete_knowledge_base_document(
    bot_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> KnowledgeBaseDeleteResponse:
    try:
        return await knowledge_base_service.delete_document(db, bot_id, document_id)
    except ValueError as exc:
        message = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception as exc:
        logger.exception(
            "KnowledgeBase.delete_error | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete knowledge base document.",
        ) from exc


@router.post(
    "/upload",
    response_model=KnowledgeBaseUploadResponse,
    summary="Upload and index raw text into a knowledge base",
)
async def upload_knowledge_base(
    payload: KnowledgeBaseUploadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeBaseUploadResponse:
    """Accept raw text, split it into chunks, embed them, and store in the vector DB."""
    try:
        bot_id = uuid.UUID(payload.knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="knowledge_base_id must be a valid bot UUID.",
        ) from exc

    assert_permission(current_user.role or UserRole.OPERATOR, Permission.BOT_KNOWLEDGE)
    await get_bot_for_workspace(bot_id=bot_id, db=db, current_user=current_user)

    try:
        return await knowledge_base_service.upload_text(
            db,
            bot_id,
            raw_text=payload.text,
            file_name=payload.file_name,
            source_type="text",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "KnowledgeBase.upload_text_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store knowledge base document.",
        ) from exc


@router.post(
    "/upload/file",
    response_model=KnowledgeBaseUploadResponse,
    summary="Upload a plain-text file into the knowledge base",
)
async def upload_knowledge_base_file(
    knowledge_base_id: str = Form(..., min_length=1, max_length=255),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeBaseUploadResponse:
    """Accept a text file upload, chunk it, and store embeddings in the vector DB."""
    try:
        bot_id = uuid.UUID(knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="knowledge_base_id must be a valid bot UUID.",
        ) from exc

    assert_permission(current_user.role or UserRole.OPERATOR, Permission.BOT_KNOWLEDGE)
    await get_bot_for_workspace(bot_id=bot_id, db=db, current_user=current_user)

    if file.content_type and not (
        file.content_type.startswith("text/")
        or file.content_type in {"application/json", "application/octet-stream"}
    ):
        logger.warning(
            "KnowledgeBase.unsupported_file_type | type={content_type}",
            content_type=file.content_type,
        )

    file_name = _normalize_upload_file_name(file)
    extension = file_name[file_name.rfind(".") :].lower() if "." in file_name else ""
    if extension and extension not in _TEXT_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only text, markdown, csv, or json files are supported.",
        )

    raw_bytes = await file.read()
    raw_text = await _decode_upload_bytes(raw_bytes)

    try:
        return await knowledge_base_service.upload_text(
            db,
            bot_id,
            raw_text=raw_text,
            file_name=file_name,
            source_type="file",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "KnowledgeBase.upload_file_error | bot_id={bot_id} file_name={file_name} error={error}",
            bot_id=bot_id,
            file_name=file_name,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store knowledge base document.",
        ) from exc
