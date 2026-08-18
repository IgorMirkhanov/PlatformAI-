"""Google Drive / Docs ingestion for per-bot RAG knowledge bases.

Fetches shared Docs, Sheets, Drive files, or folders; routes payloads through
``document_parser`` + ``text_chunker``; embeds into ChromaDB under ``bot_id``.
Failures are logged to ``BotDiagnosticLog`` and never crash the API worker.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.vector_db import delete_document_vectors
from app.models.core_models import Bot, DiagnosticErrorType, KnowledgeBaseDocument
from app.services.diagnostic_log_service import diagnostic_log_service
from app.services.document_parser import extract_text_from_bytes, ingest_document_to_chroma, split_text_into_chunks

GOOGLE_DRIVE_FORMAT = "Google Drive"
SOURCE_TYPE_GOOGLE = "google_drive"

_USER_AGENT = "MP.AI-GoogleSync/1.0"


class GoogleResourceKind(str, Enum):
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    FILE = "file"
    FOLDER = "folder"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ParsedGoogleUrl:
    kind: GoogleResourceKind
    resource_id: str
    original_url: str


@dataclass(slots=True)
class FetchedGooglePayload:
    file_name: str
    text: str
    source_url: str
    mime_hint: str | None = None


class GoogleSyncError(Exception):
    """Recoverable Google sync failure (logged to diagnostics)."""


class GoogleSyncService:
    """Asynchronous Google Drive / Docs → ChromaDB ingestion."""

    def parse_google_url(self, google_url: str) -> ParsedGoogleUrl:
        raw = (google_url or "").strip()
        if not raw:
            raise ValueError("google_url is required.")
        if not raw.startswith(("http://", "https://")):
            raw = f"https://{raw}"

        parsed = urlparse(raw)
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        query = parse_qs(parsed.query or "")

        patterns: list[tuple[GoogleResourceKind, re.Pattern[str]]] = [
            (GoogleResourceKind.DOCUMENT, re.compile(r"/document/d/([a-zA-Z0-9_-]+)")),
            (GoogleResourceKind.SPREADSHEET, re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")),
            (GoogleResourceKind.PRESENTATION, re.compile(r"/presentation/d/([a-zA-Z0-9_-]+)")),
            (GoogleResourceKind.FILE, re.compile(r"/file/d/([a-zA-Z0-9_-]+)")),
            (GoogleResourceKind.FOLDER, re.compile(r"/folders/([a-zA-Z0-9_-]+)")),
        ]
        for kind, pattern in patterns:
            match = pattern.search(path)
            if match:
                return ParsedGoogleUrl(kind=kind, resource_id=match.group(1), original_url=raw)

        id_values = query.get("id") or []
        if id_values and ("drive.google.com" in host or "docs.google.com" in host):
            kind = (
                GoogleResourceKind.FOLDER
                if "/folders" in path
                else GoogleResourceKind.FILE
            )
            return ParsedGoogleUrl(kind=kind, resource_id=id_values[0], original_url=raw)

        raise ValueError(
            "Unsupported Google URL. Provide a Docs, Sheets, Drive file, or folder link."
        )

    async def create_pending_placeholder(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        google_url: str,
    ) -> KnowledgeBaseDocument:
        bot = await self._get_bot(db, bot_id)
        parsed = self.parse_google_url(google_url)
        label = f"Google Drive ({parsed.kind.value}:{parsed.resource_id[:8]}…)"

        document = KnowledgeBaseDocument(
            bot_id=bot.id,
            file_name=label,
            source_type=SOURCE_TYPE_GOOGLE,
            format=GOOGLE_DRIVE_FORMAT,
            character_count=0,
            chunk_count=0,
            is_context_active=True,
        )
        db.add(document)
        await db.flush()
        await db.refresh(document)

        logger.info(
            "GoogleSync.pending_registered | bot_id={bot_id} document_id={document_id} "
            "kind={kind} resource_id={resource_id}",
            bot_id=bot_id,
            document_id=document.id,
            kind=parsed.kind.value,
            resource_id=parsed.resource_id,
        )
        return document

    async def sync_google_drive_folder_or_file(
        self,
        bot_id: str | uuid.UUID,
        google_url: str,
        *,
        document_id: str | uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Full sync entrypoint used by background workers.

        Opens its own DB session so FastAPI request sessions stay unbound.
        """
        resolved_bot_id = bot_id if isinstance(bot_id, uuid.UUID) else uuid.UUID(str(bot_id))
        resolved_document_id = (
            None
            if document_id is None
            else (document_id if isinstance(document_id, uuid.UUID) else uuid.UUID(str(document_id)))
        )

        async with async_session_factory() as db:
            try:
                result = await self._sync_in_session(
                    db,
                    bot_id=resolved_bot_id,
                    google_url=google_url,
                    document_id=resolved_document_id,
                )
                await db.commit()
                return result
            except Exception as exc:
                await db.rollback()
                logger.exception(
                    "GoogleSync.job_failed | bot_id={bot_id} url={url} error={error}",
                    bot_id=resolved_bot_id,
                    url=google_url,
                    error=str(exc),
                )
                await self._record_failure(
                    bot_id=resolved_bot_id,
                    google_url=google_url,
                    error=exc,
                    document_id=resolved_document_id,
                )
                return {
                    "ok": False,
                    "bot_id": str(resolved_bot_id),
                    "error": str(exc),
                }

    async def _sync_in_session(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        google_url: str,
        document_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        bot = await self._get_bot(db, bot_id)
        parsed = self.parse_google_url(google_url)

        payloads = await self._fetch_payloads(parsed)
        if not payloads:
            raise GoogleSyncError(
                "Google Drive returned no extractable text. "
                "Check sharing permissions (Anyone with the link) or set GOOGLE_API_KEY."
            )

        combined_parts = [payload.text.strip() for payload in payloads if payload.text.strip()]
        combined_text = "\n\n---\n\n".join(combined_parts).strip()
        if not combined_text:
            raise GoogleSyncError("Fetched Google assets contain no usable text.")

        display_name = payloads[0].file_name if len(payloads) == 1 else f"Google Drive folder ({len(payloads)} files)"
        chunks = split_text_into_chunks(combined_text)
        if not chunks:
            raise GoogleSyncError("Chunker produced no semantic blocks from Google content.")

        document = await self._resolve_document(
            db,
            bot_id=bot.id,
            document_id=document_id,
            display_name=display_name,
            google_url=google_url,
        )

        knowledge_base_id = str(bot.id)
        try:
            await delete_document_vectors(str(document.id), bot_id=knowledge_base_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "GoogleSync.purge_skipped | document_id={document_id} error={error}",
                document_id=document.id,
                error=str(exc),
            )

        ingest_result = await ingest_document_to_chroma(
            bot_id=knowledge_base_id,
            text=combined_text,
            source_metadata={
                "document_id": str(document.id),
                "file_name": display_name,
                "source_url": google_url[:1000],
                "source_format": GOOGLE_DRIVE_FORMAT,
                "source_type": SOURCE_TYPE_GOOGLE,
            },
        )
        stored = int(ingest_result.get("chunks_stored") or 0)

        document.file_name = display_name[:512]
        document.source_type = SOURCE_TYPE_GOOGLE
        document.format = GOOGLE_DRIVE_FORMAT
        document.character_count = len(combined_text)
        document.chunk_count = stored
        document.is_context_active = True
        await db.flush()

        from app.services.knowledge_base_service import knowledge_base_service

        await knowledge_base_service.invalidate_retrieval_cache(bot.id)

        logger.info(
            "GoogleSync.completed | bot_id={bot_id} document_id={document_id} "
            "chunks={chunks} files={files}",
            bot_id=bot.id,
            document_id=document.id,
            chunks=stored,
            files=len(payloads),
        )
        return {
            "ok": True,
            "bot_id": str(bot.id),
            "document_id": str(document.id),
            "chunks_stored": stored,
            "character_count": len(combined_text),
            "files_ingested": len(payloads),
        }

    async def _fetch_payloads(self, parsed: ParsedGoogleUrl) -> list[FetchedGooglePayload]:
        timeout = settings.GOOGLE_SYNC_TIMEOUT_SECONDS
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            if parsed.kind == GoogleResourceKind.FOLDER:
                return await self._fetch_folder(client, parsed)
            payload = await self._fetch_single_resource(client, parsed)
            return [payload] if payload else []

    async def _fetch_single_resource(
        self,
        client: httpx.AsyncClient,
        parsed: ParsedGoogleUrl,
    ) -> FetchedGooglePayload | None:
        export_url, file_name, mime_hint = self._build_export_target(parsed)
        try:
            response = await client.get(export_url)
        except httpx.HTTPError as exc:
            raise GoogleSyncError(f"Network error fetching Google asset: {exc}") from exc

        if response.status_code in {401, 403}:
            raise GoogleSyncError(
                f"Google Drive access denied (HTTP {response.status_code}). "
                "Share the file publicly or configure GOOGLE_API_KEY."
            )
        if response.status_code == 404:
            raise GoogleSyncError("Google Drive resource not found (HTTP 404).")
        if response.status_code >= 400:
            raise GoogleSyncError(
                f"Google Drive fetch failed with HTTP {response.status_code}."
            )

        content_type = (response.headers.get("content-type") or "").lower()
        raw = response.content
        text = ""

        if "text/" in content_type or "csv" in content_type or "json" in content_type:
            text = raw.decode("utf-8", errors="ignore")
        elif parsed.kind in {
            GoogleResourceKind.DOCUMENT,
            GoogleResourceKind.SPREADSHEET,
            GoogleResourceKind.PRESENTATION,
        }:
            text = raw.decode("utf-8", errors="ignore")
        else:
            # Binary Drive file — route through the standard document parser.
            guessed_name = file_name
            if "pdf" in content_type and not guessed_name.lower().endswith(".pdf"):
                guessed_name = f"{guessed_name}.pdf"
            elif (
                "word" in content_type or "officedocument.wordprocessingml" in content_type
            ) and not guessed_name.lower().endswith(".docx"):
                guessed_name = f"{guessed_name}.docx"
            try:
                text = extract_text_from_bytes(raw, guessed_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "GoogleSync.parse_bytes_failed | id={id} error={error}",
                    id=parsed.resource_id,
                    error=str(exc),
                )
                text = raw.decode("utf-8", errors="ignore")

        text = (text or "").strip()
        if not text:
            return None

        return FetchedGooglePayload(
            file_name=file_name[:512],
            text=text,
            source_url=parsed.original_url,
            mime_hint=mime_hint or content_type,
        )

    def _build_export_target(
        self,
        parsed: ParsedGoogleUrl,
    ) -> tuple[str, str, str]:
        resource_id = parsed.resource_id
        if parsed.kind == GoogleResourceKind.DOCUMENT:
            return (
                f"https://docs.google.com/document/d/{resource_id}/export?format=txt",
                f"google-doc-{resource_id}.txt",
                "text/plain",
            )
        if parsed.kind == GoogleResourceKind.SPREADSHEET:
            return (
                f"https://docs.google.com/spreadsheets/d/{resource_id}/export?format=csv",
                f"google-sheet-{resource_id}.csv",
                "text/csv",
            )
        if parsed.kind == GoogleResourceKind.PRESENTATION:
            return (
                f"https://docs.google.com/presentation/d/{resource_id}/export/txt",
                f"google-slides-{resource_id}.txt",
                "text/plain",
            )
        # Generic Drive file download (works for publicly shared files).
        return (
            f"https://drive.google.com/uc?export=download&id={resource_id}",
            f"google-drive-{resource_id}",
            "application/octet-stream",
        )

    async def _fetch_folder(
        self,
        client: httpx.AsyncClient,
        parsed: ParsedGoogleUrl,
    ) -> list[FetchedGooglePayload]:
        children = await self._list_folder_children(client, parsed.resource_id)
        if not children:
            raise GoogleSyncError(
                "Folder is empty or inaccessible. Enable link sharing or set GOOGLE_API_KEY."
            )

        limit = max(1, settings.GOOGLE_SYNC_MAX_FOLDER_FILES)
        payloads: list[FetchedGooglePayload] = []
        for child in children[:limit]:
            child_parsed = ParsedGoogleUrl(
                kind=child["kind"],
                resource_id=child["id"],
                original_url=child.get("web_link")
                or f"https://drive.google.com/file/d/{child['id']}/view",
            )
            try:
                item = await self._fetch_single_resource(client, child_parsed)
            except GoogleSyncError as exc:
                logger.warning(
                    "GoogleSync.folder_child_skipped | id={id} error={error}",
                    id=child["id"],
                    error=str(exc),
                )
                continue
            if item is not None:
                if child.get("name"):
                    item.file_name = str(child["name"])[:512]
                payloads.append(item)
        return payloads

    async def _list_folder_children(
        self,
        client: httpx.AsyncClient,
        folder_id: str,
    ) -> list[dict[str, Any]]:
        api_key = settings.GOOGLE_API_KEY
        if api_key:
            try:
                response = await client.get(
                    "https://www.googleapis.com/drive/v3/files",
                    params={
                        "q": f"'{folder_id}' in parents and trashed=false",
                        "fields": "files(id,name,mimeType,webViewLink)",
                        "pageSize": settings.GOOGLE_SYNC_MAX_FOLDER_FILES,
                        "key": api_key,
                    },
                )
                if response.status_code in {401, 403}:
                    raise GoogleSyncError(
                        f"Google Drive API denied folder listing (HTTP {response.status_code})."
                    )
                if response.status_code == 404:
                    raise GoogleSyncError("Google Drive folder not found (HTTP 404).")
                response.raise_for_status()
                files = response.json().get("files") or []
                return [
                    {
                        "id": item["id"],
                        "name": item.get("name") or item["id"],
                        "kind": self._kind_from_mime(item.get("mimeType")),
                        "web_link": item.get("webViewLink"),
                    }
                    for item in files
                    if item.get("id")
                ]
            except GoogleSyncError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "GoogleSync.api_list_failed | folder_id={folder_id} error={error}",
                    folder_id=folder_id,
                    error=str(exc),
                )

        # Fallback: scrape public folder HTML for nested resource links.
        try:
            response = await client.get(
                f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"
            )
            if response.status_code in {401, 403}:
                raise GoogleSyncError(
                    f"Google Drive folder access denied (HTTP {response.status_code})."
                )
            if response.status_code == 404:
                raise GoogleSyncError("Google Drive folder not found (HTTP 404).")
            html = response.text or ""
        except GoogleSyncError:
            raise
        except httpx.HTTPError as exc:
            raise GoogleSyncError(f"Network error listing Google folder: {exc}") from exc

        found: dict[str, dict[str, Any]] = {}
        for kind, pattern in (
            (GoogleResourceKind.DOCUMENT, r"/document/d/([a-zA-Z0-9_-]+)"),
            (GoogleResourceKind.SPREADSHEET, r"/spreadsheets/d/([a-zA-Z0-9_-]+)"),
            (GoogleResourceKind.PRESENTATION, r"/presentation/d/([a-zA-Z0-9_-]+)"),
            (GoogleResourceKind.FILE, r"/file/d/([a-zA-Z0-9_-]+)"),
        ):
            for match in re.finditer(pattern, html):
                resource_id = match.group(1)
                if resource_id == folder_id or resource_id in found:
                    continue
                found[resource_id] = {
                    "id": resource_id,
                    "name": f"google-{kind.value}-{resource_id}",
                    "kind": kind,
                    "web_link": None,
                }
        return list(found.values())

    @staticmethod
    def _kind_from_mime(mime: str | None) -> GoogleResourceKind:
        value = (mime or "").lower()
        if value == "application/vnd.google-apps.document":
            return GoogleResourceKind.DOCUMENT
        if value == "application/vnd.google-apps.spreadsheet":
            return GoogleResourceKind.SPREADSHEET
        if value == "application/vnd.google-apps.presentation":
            return GoogleResourceKind.PRESENTATION
        if value == "application/vnd.google-apps.folder":
            return GoogleResourceKind.FOLDER
        return GoogleResourceKind.FILE

    async def _resolve_document(
        self,
        db: AsyncSession,
        *,
        bot_id: uuid.UUID,
        document_id: uuid.UUID | None,
        display_name: str,
        google_url: str,
    ) -> KnowledgeBaseDocument:
        if document_id is not None:
            result = await db.execute(
                select(KnowledgeBaseDocument).where(
                    KnowledgeBaseDocument.id == document_id,
                    KnowledgeBaseDocument.bot_id == bot_id,
                )
            )
            document = result.scalar_one_or_none()
            if document is not None:
                return document

        document = KnowledgeBaseDocument(
            bot_id=bot_id,
            file_name=display_name[:512],
            source_type=SOURCE_TYPE_GOOGLE,
            format=GOOGLE_DRIVE_FORMAT,
            character_count=0,
            chunk_count=0,
            is_context_active=True,
        )
        db.add(document)
        await db.flush()
        logger.info(
            "GoogleSync.placeholder_created_late | bot_id={bot_id} document_id={document_id} url={url}",
            bot_id=bot_id,
            document_id=document.id,
            url=google_url,
        )
        return document

    async def _get_bot(self, db: AsyncSession, bot_id: uuid.UUID) -> Bot:
        result = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()
        if bot is None:
            raise ValueError(f"Bot '{bot_id}' not found.")
        return bot

    async def _record_failure(
        self,
        *,
        bot_id: uuid.UUID,
        google_url: str,
        error: Exception,
        document_id: uuid.UUID | None,
    ) -> None:
        message = (
            f"Google Drive sync failed for '{google_url[:300]}': {error}"
            + (f" (document_id={document_id})" if document_id else "")
        )
        try:
            diagnostic_log_service.schedule_log(
                bot_id=bot_id,
                error_type=DiagnosticErrorType.GOOGLE_SYNC_FAILED,
                error_message=message,
                node_id="google-sync",
            )
        except Exception as diag_exc:  # noqa: BLE001
            logger.error(
                "GoogleSync.diagnostic_failed | bot_id={bot_id} error={error}",
                bot_id=bot_id,
                error=str(diag_exc),
            )


google_sync_service = GoogleSyncService()


async def sync_google_drive_folder_or_file(
    bot_id: str,
    google_url: str,
    *,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Module-level async entry used by background tasks and scripts."""
    return await google_sync_service.sync_google_drive_folder_or_file(
        bot_id,
        google_url,
        document_id=document_id,
    )
