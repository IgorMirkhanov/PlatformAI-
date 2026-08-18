"""Safe outbound media delivery for Telegram / WhatsApp with text-only fallback."""

from __future__ import annotations

import mimetypes
import uuid
from typing import Any, Callable, Awaitable
from urllib.parse import urlparse

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import DiagnosticErrorType
from app.schemas.media_schemas import MediaAttachment, MediaKind
from app.services.diagnostic_log_service import diagnostic_log_service


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".m4a", ".aac"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".zip"}

HIGH_RELEVANCE_THRESHOLD = 0.72

MEDIA_METADATA_KEYS = (
    "source_file_url",
    "image_attachment",
    "file_url",
    "media_url",
    "attachment_url",
    "document_url",
    "image_url",
)


def infer_media_kind(url: str, *, mime_type: str | None = None, hint: str | None = None) -> MediaKind:
    """Classify a URL / MIME hint into image | document | video | audio."""
    if hint in {"image", "document", "video", "audio"}:
        return hint  # type: ignore[return-value]

    path = urlparse(url).path.lower()
    for ext in IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return "image"
    for ext in VIDEO_EXTENSIONS:
        if path.endswith(ext):
            return "video"
    for ext in AUDIO_EXTENSIONS:
        if path.endswith(ext):
            return "audio"
    for ext in DOCUMENT_EXTENSIONS:
        if path.endswith(ext):
            return "document"

    mime = (mime_type or mimetypes.guess_type(url)[0] or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "document"


def filename_from_url(url: str) -> str | None:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1].strip()
    return name or None


async def probe_media_url(url: str, *, timeout: float = 8.0) -> bool:
    """Return True when the remote URL looks reachable (HEAD/GET soft probe)."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                head = await client.head(url)
                if head.status_code < 400:
                    return True
                if head.status_code in {405, 501}:
                    # Some CDNs reject HEAD — fall through to ranged GET.
                    pass
                elif head.status_code >= 400:
                    return False
            except httpx.HTTPError:
                pass

            get = await client.get(url, headers={"Range": "bytes=0-0"})
            return get.status_code < 400
    except Exception as exc:
        logger.warning(
            "MediaDispatch.probe_failed | url={url} error={error}",
            url=url[:200],
            error=str(exc),
        )
        return False


async def log_media_failure(
    db: AsyncSession | None,
    *,
    bot_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    url: str,
    detail: str,
) -> None:
    message = f"Media attachment delivery failed for {url[:300]}: {detail}"[:4000]
    if bot_id is None:
        logger.warning("MediaDispatch.no_bot_for_diagnostic | detail={detail}", detail=message)
        return

    try:
        if db is not None:
            await diagnostic_log_service.log(
                db,
                bot_id=bot_id,
                client_id=client_id,
                error_type=DiagnosticErrorType.MESSENGER_API_ERROR,
                error_message=message,
                node_id="media_attachment",
            )
        else:
            diagnostic_log_service.schedule_log(
                bot_id=bot_id,
                client_id=client_id,
                error_type=DiagnosticErrorType.MESSENGER_API_ERROR,
                error_message=message,
                node_id="media_attachment",
            )
    except Exception as log_exc:
        logger.warning(
            "MediaDispatch.diagnostic_failed | error={error}",
            error=str(log_exc),
        )


SendAttachmentFn = Callable[[MediaAttachment], Awaitable[None]]


async def deliver_attachments_safely(
    attachments: list[MediaAttachment],
    *,
    send_fn: SendAttachmentFn,
    bot_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    db: AsyncSession | None,
    probe: bool = True,
) -> list[MediaAttachment]:
    """
    Attempt each attachment independently.

    Broken / unreachable URLs are skipped after a diagnostic warning — never
    raise, so the parent webhook task can still deliver the text reply.
    """
    delivered: list[MediaAttachment] = []
    for attachment in attachments:
        try:
            if probe and not await probe_media_url(attachment.url):
                await log_media_failure(
                    db,
                    bot_id=bot_id,
                    client_id=client_id,
                    url=attachment.url,
                    detail="URL unreachable or returned an error status",
                )
                continue
            await send_fn(attachment)
            delivered.append(attachment)
        except Exception as exc:
            logger.warning(
                "MediaDispatch.send_failed | url={url} error={error}",
                url=attachment.url[:200],
                error=str(exc),
            )
            await log_media_failure(
                db,
                bot_id=bot_id,
                client_id=client_id,
                url=attachment.url,
                detail=str(exc),
            )
    return delivered


def dedupe_attachments(attachments: list[MediaAttachment]) -> list[MediaAttachment]:
    seen: set[str] = set()
    unique: list[MediaAttachment] = []
    for item in attachments:
        key = item.url.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def extract_urls_from_metadata(metadata: dict[str, Any] | None) -> list[tuple[str, str | None]]:
    """Return (url, preferred_kind_hint) pairs from Chroma chunk metadata."""
    if not metadata:
        return []
    found: list[tuple[str, str | None]] = []
    for key in MEDIA_METADATA_KEYS:
        raw = metadata.get(key)
        if not isinstance(raw, str):
            continue
        url = raw.strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        hint = "image" if "image" in key.lower() else None
        found.append((url, hint))
    return found
