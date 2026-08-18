"""Document extraction, semantic chunking, and ChromaDB ingest for per-bot RAG.

Pipeline:
  1. Extract text from TXT / PDF / DOCX uploads or remote HTTP(S) links
  2. Split into overlapping semantic / recursive-character chunks (default 500 / 50)
  3. Embed with OpenAI ``text-embedding-3-small`` and write into an isolated
     Chroma collection named ``bot_{bot_id}``
"""

from __future__ import annotations

import io
import re
import uuid
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

from app.core.config import settings


# ---------------------------------------------------------------------------
# Text extraction (uploads + remote links)
# ---------------------------------------------------------------------------


def extract_text_from_bytes(raw_bytes: bytes, file_name: str) -> str:
    """Extract plain text from an uploaded file (TXT, PDF, DOCX, and common text formats)."""
    extension = file_name[file_name.rfind(".") :].lower() if "." in file_name else ""
    if extension in {".txt", ".md", ".markdown", ".csv", ".json"}:
        return _decode_text_bytes(raw_bytes)
    if extension == ".pdf":
        return _extract_pdf_text(raw_bytes)
    if extension == ".docx":
        return _extract_docx_text(raw_bytes)
    return _decode_text_bytes(raw_bytes)


def fetch_url_text(
    url: str,
    *,
    depth_limit: int = 1,
    timeout: float = 20.0,
    max_pages: int = 10,
) -> str:
    """Fetch and extract text from a remote link (optional shallow same-host crawl)."""
    from app.core.url_safety import assert_safe_public_http_url

    normalized = assert_safe_public_http_url(url)

    safe_depth = max(1, min(depth_limit, 5))
    if safe_depth <= 1:
        return _fetch_single_page(normalized, timeout=timeout)

    parsed_root = urlparse(normalized)
    root_host = parsed_root.netloc
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(normalized, 0)]
    collected: list[str] = []

    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        while queue and len(visited) < max_pages:
            current_url, depth = queue.pop(0)
            if current_url in visited:
                continue
            try:
                current_url = assert_safe_public_http_url(current_url)
            except ValueError:
                continue
            visited.add(current_url)

            try:
                response = client.get(
                    current_url,
                    headers={"User-Agent": "MP.AI-KnowledgeBot/1.0"},
                )
                # Manual redirect follow with re-validation (SSRF-safe).
                hops = 0
                while response.is_redirect and hops < 5:
                    location = response.headers.get("location")
                    if not location:
                        break
                    next_url = urljoin(str(response.url), location)
                    next_url = assert_safe_public_http_url(next_url)
                    response = client.get(
                        next_url,
                        headers={"User-Agent": "MP.AI-KnowledgeBot/1.0"},
                    )
                    hops += 1
                response.raise_for_status()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "DocumentParser.page_failed | url={url} error={error}",
                    url=current_url,
                    error=str(exc),
                )
                continue

            content_type = response.headers.get("content-type", "").lower()
            html = response.text if "html" in content_type else ""
            page_text = _html_to_text(html) if html else response.text.strip()
            if page_text:
                collected.append(page_text)

            if depth + 1 >= safe_depth or not html:
                continue

            for link in _extract_same_host_links(html, str(response.url), root_host):
                if link not in visited:
                    queue.append((link, depth + 1))

    combined = "\n\n".join(collected).strip()
    if not combined:
        raise ValueError("Website crawl returned no extractable text.")
    return combined


# ---------------------------------------------------------------------------
# Semantic / recursive character splitter
# ---------------------------------------------------------------------------


class RecursiveCharacterTextSplitter:
    """
    LangChain-style recursive character splitter.

    Tries to cut on semantic boundaries (paragraphs → lines → sentences → words)
    before falling back to hard character windows, with configurable overlap.
    """

    DEFAULT_SEPARATORS: tuple[str, ...] = (
        "\n\n",
        "\n",
        ". ",
        "! ",
        "? ",
        "; ",
        ", ",
        " ",
        "",
    )

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        separators: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.chunk_size = max(50, int(chunk_size or settings.KB_CHUNK_SIZE or 500))
        overlap = int(chunk_overlap if chunk_overlap is not None else settings.KB_CHUNK_OVERLAP or 50)
        self.chunk_overlap = max(0, min(overlap, self.chunk_size // 2))
        self.separators = list(separators) if separators is not None else list(self.DEFAULT_SEPARATORS)

    def split_text(self, text: str) -> list[str]:
        normalized = _normalize_whitespace(text)
        if not normalized:
            return []
        if len(normalized) <= self.chunk_size:
            return [normalized]

        chunks = self._split_recursive(normalized, self.separators)
        return self._merge_small_chunks([chunk.strip() for chunk in chunks if chunk.strip()])

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        if len(text) <= self.chunk_size:
            return [text] if text else []

        separator = separators[-1] if separators else ""
        next_separators: list[str] = []
        for index, candidate in enumerate(separators):
            if candidate == "":
                separator = ""
                next_separators = []
                break
            if candidate in text:
                separator = candidate
                next_separators = separators[index + 1 :]
                break

        if separator == "":
            return self._hard_split(text)

        parts = text.split(separator)
        good: list[str] = []
        pending = ""

        for part in parts:
            piece = part if separator == "" else f"{part}{separator}"
            candidate = f"{pending}{piece}" if pending else piece
            if len(candidate) <= self.chunk_size:
                pending = candidate
                continue

            if pending:
                good.extend(self._split_recursive(pending, next_separators or [""]))
            if len(piece) > self.chunk_size:
                good.extend(self._split_recursive(piece, next_separators or [""]))
                pending = ""
            else:
                pending = piece

        if pending:
            good.extend(self._split_recursive(pending, next_separators or [""]))
        return good

    def _hard_split(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(end - self.chunk_overlap, start + 1)
        return chunks

    def _merge_small_chunks(self, chunks: list[str]) -> list[str]:
        """Apply overlap windows across recursive pieces for denser retrieval."""
        if not chunks:
            return []

        # First flatten oversized leftovers, then build overlapping windows.
        flat: list[str] = []
        for chunk in chunks:
            if len(chunk) <= self.chunk_size:
                flat.append(chunk)
            else:
                flat.extend(self._hard_split(chunk))

        if len(flat) == 1:
            return flat

        # Re-join with separators stripped and re-window with overlap for consistency
        # when recursive cuts produced many tiny fragments.
        joined = "\n\n".join(flat)
        if len(joined) <= self.chunk_size:
            return [joined]

        windowed: list[str] = []
        start = 0
        while start < len(joined):
            end = min(start + self.chunk_size, len(joined))
            # Prefer breaking on whitespace near the end of the window.
            if end < len(joined):
                soft = joined.rfind(" ", start + self.chunk_size // 2, end)
                if soft > start:
                    end = soft
            piece = joined[start:end].strip()
            if piece:
                windowed.append(piece)
            if end >= len(joined):
                break
            start = max(end - self.chunk_overlap, start + 1)
        return windowed or flat


def split_text_into_chunks(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Public chunking helper used by the knowledge-base upload pipeline."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
    )
    chunks = splitter.split_text(text)
    logger.debug(
        "DocumentParser.chunked | chars={chars} chunks={count} size={size} overlap={overlap}",
        chars=len(text or ""),
        count=len(chunks),
        size=splitter.chunk_size,
        overlap=splitter.chunk_overlap,
    )
    return chunks


# ---------------------------------------------------------------------------
# Embedding + isolated Chroma write
# ---------------------------------------------------------------------------


def bot_collection_name(bot_id: str) -> str:
    """Stable Chroma collection name for a bot's private vector namespace."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", str(bot_id).strip())
    return f"bot_{cleaned}"[:128]


async def ingest_document_to_chroma(
    bot_id: str,
    text: str,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Chunk → embed (``text-embedding-3-small``) → write into ``bot_{bot_id}`` collection.

    Returns a summary dict with ``chunks_stored``, ``document_id``, ``collection``.
    """
    from app.core.embeddings import embed_texts
    from app.core.vector_db import add_chunks_to_bot_collection

    meta = dict(source_metadata or {})
    document_id = str(meta.get("document_id") or uuid.uuid4())
    file_name = str(meta.get("file_name") or meta.get("source") or "document.txt")

    chunks = split_text_into_chunks(text)
    if not chunks:
        logger.warning(
            "DocumentParser.ingest_empty | bot_id={bot_id} document_id={document_id}",
            bot_id=bot_id,
            document_id=document_id,
        )
        return {
            "bot_id": str(bot_id),
            "document_id": document_id,
            "collection": bot_collection_name(bot_id),
            "chunks_stored": 0,
            "file_name": file_name,
        }

    logger.info(
        "DocumentParser.ingest_start | bot_id={bot_id} document_id={document_id} chunks={count} model={model}",
        bot_id=bot_id,
        document_id=document_id,
        count=len(chunks),
        model=settings.OPENAI_EMBEDDING_MODEL,
    )

    embeddings = await embed_texts(chunks)
    stored = await add_chunks_to_bot_collection(
        bot_id=str(bot_id),
        document_id=document_id,
        file_name=file_name,
        text_chunks=chunks,
        embeddings=embeddings,
        extra_metadata=meta,
    )

    logger.info(
        "DocumentParser.ingest_complete | bot_id={bot_id} document_id={document_id} chunks={count} collection={collection}",
        bot_id=bot_id,
        document_id=document_id,
        count=stored,
        collection=bot_collection_name(bot_id),
    )
    return {
        "bot_id": str(bot_id),
        "document_id": document_id,
        "collection": bot_collection_name(bot_id),
        "chunks_stored": stored,
        "file_name": file_name,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_whitespace(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _fetch_single_page(url: str, *, timeout: float = 20.0) -> str:
    from app.core.url_safety import assert_safe_public_http_url

    safe_url = assert_safe_public_http_url(url)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.get(safe_url, headers={"User-Agent": "MP.AI-KnowledgeBot/1.0"})
        hops = 0
        while response.is_redirect and hops < 5:
            location = response.headers.get("location")
            if not location:
                break
            next_url = assert_safe_public_http_url(urljoin(str(response.url), location))
            response = client.get(next_url, headers={"User-Agent": "MP.AI-KnowledgeBot/1.0"})
            hops += 1
        response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type:
        return _html_to_text(response.text)
    # Binary remote documents (PDF / DOCX)
    path = urlparse(str(response.url)).path.lower()
    if path.endswith(".pdf"):
        return _extract_pdf_text(response.content)
    if path.endswith(".docx"):
        return _extract_docx_text(response.content)
    return response.text.strip()


def _extract_same_host_links(html: str, base_url: str, root_host: str) -> list[str]:
    hrefs = re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\']', html)
    links: list[str] = []
    for href in hrefs:
        absolute = urljoin(base_url, href.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc != root_host:
            continue
        normalized = absolute.split("#", 1)[0]
        if normalized and normalized not in links:
            links.append(normalized)
    return links


def _decode_text_bytes(raw_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode uploaded file as text.")


def _extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF parsing is unavailable on the server.") from exc

    reader = PdfReader(io.BytesIO(raw_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError("PDF does not contain extractable text.")
    return text


def _extract_docx_text(raw_bytes: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise ValueError("DOCX parsing is unavailable on the server.") from exc

    document = Document(io.BytesIO(raw_bytes))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    text = "\n".join(paragraphs).strip()
    if not text:
        raise ValueError("DOCX does not contain extractable text.")
    return text


def _html_to_text(html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    cleaned = re.sub(r"(?is)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = unescape(cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()
