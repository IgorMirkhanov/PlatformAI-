import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_bot_access
from app.core.database import get_db
from app.core.rbac import Permission
from app.models.core_models import Bot
from app.schemas.knowledge_base_schemas import (
    BotKnowledgeDocumentToggleRequest,
    BotKnowledgeReindexRequest,
    BotKnowledgeReindexResponse,
    BotKnowledgeToggleRequest,
    BotKnowledgeToggleResponse,
    BotKnowledgeUploadResponse,
    GoogleSyncAcceptedResponse,
    GoogleSyncRequest,
    KnowledgeAsyncUploadResponse,
    KnowledgeBaseChunksResponse,
    KnowledgeBaseDeleteResponse,
    KnowledgeBaseDocumentListResponse,
)
from app.services.bot_management_service import bot_management_service
from app.services.document_parser import extract_text_from_bytes, fetch_url_text
from app.services.google_sync_service import google_sync_service, sync_google_drive_folder_or_file
from app.services.knowledge_base_service import knowledge_base_service
from app.services.rag.ingestion import knowledge_ingestion_service

router = APIRouter(prefix="/bots", tags=["bot-knowledge"])

_SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".pdf", ".docx"}


def _normalize_upload_file_name(file: UploadFile) -> str:
    from pathlib import Path

    raw = (file.filename or "uploaded-document.txt").strip() or "uploaded-document.txt"
    name = Path(raw).name
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-")
    return safe or "uploaded-document.txt"


@router.get(
    "/{bot_id}/knowledge/documents",
    response_model=KnowledgeBaseDocumentListResponse,
    summary="List knowledge base assets for a bot",
)
async def list_bot_knowledge_documents(
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
            "BotKnowledge.list_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load knowledge base documents.",
        ) from exc


@router.get(
    "/{bot_id}/knowledge/documents/{document_id}/chunks",
    response_model=KnowledgeBaseChunksResponse,
    summary="Inspect semantic chunks stored in ChromaDB for a document",
)
async def list_bot_knowledge_chunks(
    bot_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> KnowledgeBaseChunksResponse:
    try:
        return await knowledge_base_service.get_document_chunks(db, bot_id, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotKnowledge.chunks_error | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load document chunks.",
        ) from exc


@router.post(
    "/{bot_id}/knowledge/upload/async",
    response_model=KnowledgeAsyncUploadResponse,
    summary="Enqueue PDF/DOCX/text ingest into Chroma via Celery",
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_bot_knowledge_async(
    bot_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> KnowledgeAsyncUploadResponse:
    """Long-running ingest — returns Celery task id + PENDING document id."""
    upload_name = _normalize_upload_file_name(file)
    extension = upload_name[upload_name.rfind(".") :].lower() if "." in upload_name else ""
    if extension and extension not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Supported formats: PDF, TXT, DOCX, MD, CSV, JSON.",
        )
    raw_bytes = await file.read()
    try:
        result = await knowledge_ingestion_service.enqueue_file_ingest(
            db,
            bot_id,
            filename=upload_name,
            content=raw_bytes,
            content_type=file.content_type,
            metadata={"uploaded_by": str(current_user.id)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotKnowledge.async_upload_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
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

@router.post(
    "/{bot_id}/knowledge/upload",
    response_model=BotKnowledgeUploadResponse,
    summary="Upload, crawl, or paste knowledge into ChromaDB",
)
async def upload_bot_knowledge(
    bot_id: uuid.UUID,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    text: str | None = Form(default=None),
    file_name: str | None = Form(default=None),
    crawl_depth: int = Form(default=1),
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> BotKnowledgeUploadResponse:
    try:
        if file is not None:
            upload_name = _normalize_upload_file_name(file)
            extension = upload_name[upload_name.rfind(".") :].lower() if "." in upload_name else ""
            if extension and extension not in _SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Supported formats: PDF, TXT, DOCX, MD, CSV, JSON.",
                )
            raw_bytes = await file.read()
            raw_text = extract_text_from_bytes(raw_bytes, upload_name)
            response = await knowledge_base_service.upload_text(
                db,
                bot_id,
                raw_text=raw_text,
                file_name=upload_name,
                source_type="file",
            )
            return BotKnowledgeUploadResponse(
                **response.model_dump(),
                source_type="file",
            )

        if url and url.strip():
            normalized_url = url.strip()
            safe_depth = max(1, min(crawl_depth, 5))
            crawled_text = fetch_url_text(normalized_url, depth_limit=safe_depth)
            derived_name = file_name.strip() if file_name and file_name.strip() else normalized_url
            response = await knowledge_base_service.upload_text(
                db,
                bot_id,
                raw_text=crawled_text,
                file_name=derived_name,
                source_type="web",
            )
            return BotKnowledgeUploadResponse(
                **response.model_dump(),
                source_type="web",
            )

        if text and text.strip():
            response = await knowledge_base_service.upload_text(
                db,
                bot_id,
                raw_text=text.strip(),
                file_name=(file_name or "manual-entry.txt").strip() or "manual-entry.txt",
                source_type="text",
            )
            return BotKnowledgeUploadResponse(
                **response.model_dump(),
                source_type="text",
            )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide a file, website URL, or raw text payload.",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotKnowledge.upload_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store knowledge base document.",
        ) from exc


@router.post(
    "/{bot_id}/knowledge/google-sync",
    response_model=GoogleSyncAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a Google Drive file or folder into the bot knowledge base",
)
async def sync_bot_knowledge_from_google(
    bot_id: uuid.UUID,
    payload: GoogleSyncRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> GoogleSyncAcceptedResponse:
    """Validate access, register a pending Google Drive ledger row, and sync in background."""
    google_url = payload.google_url.strip()
    try:
        # Fail fast on malformed URLs before accepting the job.
        google_sync_service.parse_google_url(google_url)
        document = await google_sync_service.create_pending_placeholder(
            db,
            bot_id=bot_id,
            google_url=google_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotKnowledge.google_sync_init_error | bot_id={bot_id} error={error}",
            bot_id=bot_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start Google Drive synchronization.",
        ) from exc

    background_tasks.add_task(
        sync_google_drive_folder_or_file,
        str(bot_id),
        google_url,
        document_id=str(document.id),
    )

    logger.info(
        "BotKnowledge.google_sync_accepted | bot_id={bot_id} document_id={document_id} "
        "user_id={user_id} company_id={company_id}",
        bot_id=bot_id,
        document_id=document.id,
        user_id=current_user.id,
        company_id=getattr(current_user, "company_id", None),
    )

    return GoogleSyncAcceptedResponse(
        bot_id=bot_id,
        document_id=document.id,
        google_url=google_url,
        format="Google Drive",
        message="Синхронизация с Google Диском запущена в фоновом режиме",
    )


@router.post(
    "/{bot_id}/knowledge/{document_id}/reindex",
    response_model=BotKnowledgeReindexResponse,
    summary="Re-crawl and reindex a web knowledge document without deleting the entry",
)
async def reindex_bot_knowledge_document(
    bot_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: BotKnowledgeReindexRequest = BotKnowledgeReindexRequest(),
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> BotKnowledgeReindexResponse:
    try:
        result = await knowledge_base_service.reindex_document(
            db,
            bot_id,
            document_id,
            crawl_depth=payload.crawl_depth,
        )
        return BotKnowledgeReindexResponse(
            bot_id=bot_id,
            document_id=result.document_id,
            file_name=result.file_name,
            character_count=result.character_count,
            chunks_stored=result.chunks_stored,
            message=result.message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotKnowledge.reindex_error | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reindex knowledge document.",
        ) from exc


@router.patch(
    "/{bot_id}/knowledge/{document_id}/toggle",
    response_model=BotKnowledgeToggleResponse,
    summary="Toggle document RAG visibility by path document_id (canonical)",
)
async def toggle_bot_knowledge_document(
    bot_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: BotKnowledgeDocumentToggleRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> BotKnowledgeToggleResponse:
    try:
        return await bot_management_service.toggle_knowledge_document_context(
            db=db,
            bot_id=bot_id,
            document_id=document_id,
            is_context_active=payload.is_context_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotKnowledge.toggle_path_error | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update knowledge document visibility.",
        ) from exc


@router.patch(
    "/{bot_id}/knowledge/toggle",
    response_model=BotKnowledgeToggleResponse,
    summary="Toggle whether a document participates in runtime RAG search",
)
async def toggle_bot_knowledge_context(
    bot_id: uuid.UUID,
    payload: BotKnowledgeToggleRequest,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> BotKnowledgeToggleResponse:
    try:
        return await bot_management_service.toggle_knowledge_document_context(
            db=db,
            bot_id=bot_id,
            document_id=payload.document_id,
            is_context_active=payload.is_context_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotKnowledge.toggle_error | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=payload.document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update knowledge document visibility.",
        ) from exc


@router.delete(
    "/{bot_id}/knowledge/documents/{document_id}",
    response_model=KnowledgeBaseDeleteResponse,
    summary="Delete a knowledge asset and purge ChromaDB vectors",
)
async def delete_bot_knowledge_document(
    bot_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> KnowledgeBaseDeleteResponse:
    try:
        from app.services.bot_workspace_config import get_workspace, set_workspace

        bot = await bot_management_service._get_bot(db, bot_id)
        workspace = get_workspace(bot)
        doc_id = str(document_id)
        changed = False
        for item in workspace["agent_rag"]:
            ids = [str(x) for x in (item.get("document_ids") or [])]
            if doc_id in ids:
                item["document_ids"] = [x for x in ids if x != doc_id]
                changed = True
        if changed:
            set_workspace(bot, workspace)
        return await knowledge_base_service.delete_document(db, bot_id, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "BotKnowledge.delete_error | bot_id={bot_id} document_id={document_id} error={error}",
            bot_id=bot_id,
            document_id=document_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete knowledge base document.",
        ) from exc


class AgentRagPayload(BaseModel):
    function_name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=4000)
    document_ids: list[str] | None = None


@router.get("/{bot_id}/knowledge/agent-rag")
async def list_agent_rag(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> dict:
    from app.services.bot_workspace_config import get_workspace

    bot = await bot_management_service._get_bot(db, bot_id)
    workspace = get_workspace(bot)
    return {"bot_id": str(bot_id), "items": workspace["agent_rag"]}


@router.post("/{bot_id}/knowledge/agent-rag", status_code=status.HTTP_201_CREATED)
async def create_agent_rag(
    bot_id: uuid.UUID,
    payload: AgentRagPayload,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> dict:
    from app.services.bot_workspace_config import (
        get_workspace,
        new_id,
        set_workspace,
        validate_function_name,
    )

    bot = await bot_management_service._get_bot(db, bot_id)
    workspace = get_workspace(bot)
    name = validate_function_name(payload.function_name)
    if any(str(item.get("function_name")) == name for item in workspace["agent_rag"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A knowledge collection with this function name already exists.",
        )
    item = {
        "id": new_id(),
        "function_name": name,
        "description": payload.description.strip(),
        "document_ids": list(payload.document_ids or []),
    }
    workspace["agent_rag"].append(item)
    set_workspace(bot, workspace)
    await db.flush()
    return item


@router.patch("/{bot_id}/knowledge/agent-rag/{rag_id}")
async def update_agent_rag(
    bot_id: uuid.UUID,
    rag_id: str,
    payload: AgentRagPayload,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> dict:
    from app.services.bot_workspace_config import (
        get_workspace,
        set_workspace,
        validate_function_name,
    )

    bot = await bot_management_service._get_bot(db, bot_id)
    workspace = get_workspace(bot)
    name = validate_function_name(payload.function_name)
    updated = None
    for item in workspace["agent_rag"]:
        if str(item.get("id")) != rag_id:
            if str(item.get("function_name")) == name:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A knowledge collection with this function name already exists.",
                )
            continue
        item["function_name"] = name
        item["description"] = payload.description.strip()
        if payload.document_ids is not None:
            item["document_ids"] = list(payload.document_ids)
        updated = item
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent RAG collection not found.")
    set_workspace(bot, workspace)
    await db.flush()
    return updated


@router.delete("/{bot_id}/knowledge/agent-rag/{rag_id}")
async def delete_agent_rag(
    bot_id: uuid.UUID,
    rag_id: str,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_KNOWLEDGE)),
) -> dict:
    from app.services.bot_workspace_config import get_workspace, set_workspace

    bot = await bot_management_service._get_bot(db, bot_id)
    workspace = get_workspace(bot)
    before = len(workspace["agent_rag"])
    workspace["agent_rag"] = [
        item for item in workspace["agent_rag"] if str(item.get("id")) != rag_id
    ]
    if len(workspace["agent_rag"]) == before:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent RAG collection not found.")
    set_workspace(bot, workspace)
    await db.flush()
    return {"deleted": True, "id": rag_id}


@router.get("/{bot_id}/knowledge/openai-tools")
async def bot_openai_tools(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _bot: Bot = Depends(require_bot_access(Permission.BOT_FUNCTIONS)),
) -> dict:
    from app.services.bot_workspace_config import openai_tools_for_bot

    bot = await bot_management_service._get_bot(db, bot_id)
    return {"bot_id": str(bot_id), "tools": openai_tools_for_bot(bot)}

