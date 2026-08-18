"""Kaspi receipt OCR / text extraction for automated deposit verification.

Defensive by design: corrupted files, missing OCR binaries, and non-Kaspi
payloads never raise — callers receive ``None`` or a sparsely populated
``KaspiReceiptData`` instance instead.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from loguru import logger

# ---------------------------------------------------------------------------
# Regex matrix — Kaspi Business / transfer receipts (RU)
# ---------------------------------------------------------------------------

_TX_LABEL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"(?:номер\s+перевода|номер\s+транзакции|транзакция|transaction\s*(?:id|№|#)?)"
        r"\s*[:№#]?\s*([0-9]{10,12})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:код\s+операции|id\s+операции)\s*[:№#]?\s*([0-9]{10,12})",
        re.IGNORECASE,
    ),
)

_TX_BARE_DIGIT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(\d{10,12})(?!\d)",
)

_AMOUNT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"сумма\s*[:\-]?\s*([\d\s\u00a0]+(?:[.,]\d{1,2})?)\s*(?:₸|тенге|kzt)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"([\d\s\u00a0]+(?:[.,]\d{1,2})?)\s*(?:₸|тенге|kzt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:₸|тенге|kzt)\s*([\d\s\u00a0]+(?:[.,]\d{1,2})?)",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True, slots=True)
class KaspiReceiptData:
    """Structured fields extracted from a Kaspi payment receipt."""

    transaction_id: str | None = None
    amount: Decimal | None = None
    raw_text: str | None = None
    source: str = "none"

    @property
    def is_complete(self) -> bool:
        return bool(self.transaction_id) and self.amount is not None and self.amount > 0


def extract_kaspi_receipt_data(file_bytes: bytes, filename: str) -> KaspiReceiptData | None:
    """Scan receipt bytes for Kaspi transaction id + amount.

    Never raises for corrupt / non-Kaspi / image-only payloads. Returns
    ``None`` only when no usable text layer can be obtained at all;
    otherwise returns a (possibly incomplete) ``KaspiReceiptData``.
    """
    if not file_bytes:
        return None

    name = (filename or "receipt.bin").strip() or "receipt.bin"
    lower = name.lower()

    try:
        text, source = _extract_text_layer(file_bytes, lower)
    except Exception as exc:  # noqa: BLE001 — defensive boundary
        logger.warning(
            "OCR.extract_failed | filename={filename} error={error}",
            filename=name,
            error=str(exc),
        )
        return None

    if not text or not text.strip():
        return None

    try:
        transaction_id = _match_transaction_id(text)
        amount = _match_amount(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "OCR.parse_failed | filename={filename} error={error}",
            filename=name,
            error=str(exc),
        )
        return KaspiReceiptData(raw_text=text[:4000], source=source)

    result = KaspiReceiptData(
        transaction_id=transaction_id,
        amount=amount,
        raw_text=text[:4000],
        source=source,
    )
    logger.info(
        "OCR.kaspi_parsed | filename={filename} source={source} "
        "tx_id={tx_id} amount={amount}",
        filename=name,
        source=source,
        tx_id=transaction_id,
        amount=str(amount) if amount is not None else None,
    )
    return result


def _extract_text_layer(file_bytes: bytes, lower_name: str) -> tuple[str, str]:
    """Best-effort text extraction without requiring native OCR binaries."""
    if lower_name.endswith(".pdf") or file_bytes[:4] == b"%PDF":
        pdf_text = _extract_pdf_text(file_bytes)
        if pdf_text.strip():
            return pdf_text, "pdf_text"

    # Plain-text / HTML dumps exported from banking apps.
    if lower_name.endswith((".txt", ".html", ".htm", ".csv")):
        decoded = _safe_decode(file_bytes)
        if decoded.strip():
            return decoded, "plain_text"

    # Some "image" uploads are actually mislabeled text; try UTF-8 peek.
    if not lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        decoded = _safe_decode(file_bytes)
        if _looks_like_receipt_text(decoded):
            return decoded, "plain_text"

    # Raw images: optional soft OCR if pytesseract+Pillow are installed.
    if lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) or _looks_like_image(
        file_bytes
    ):
        ocr_text = _try_optional_image_ocr(file_bytes)
        if ocr_text and ocr_text.strip():
            return ocr_text, "image_ocr"

        meta = _extract_image_metadata_text(file_bytes)
        if meta and _looks_like_receipt_text(meta):
            return meta, "image_metadata"
        return "", "image_unavailable"

    decoded = _safe_decode(file_bytes)
    return decoded, "binary_decode"


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.debug("OCR.pdf_skip | pypdf unavailable")
        return _safe_decode(file_bytes)

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        chunks: list[str] = []
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                page_text = ""
            if page_text:
                chunks.append(page_text)
        return "\n".join(chunks)
    except Exception as exc:  # noqa: BLE001
        logger.debug("OCR.pdf_corrupt | error={error}", error=str(exc))
        return ""


def _try_optional_image_ocr(file_bytes: bytes) -> str:
    """Use pytesseract only when both Pillow and the binary are present."""
    try:
        from PIL import Image  # type: ignore[import-not-found]
        import pytesseract  # type: ignore[import-not-found]
    except ImportError:
        return ""

    try:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image, lang="rus+eng")
        return text or ""
    except Exception as exc:  # noqa: BLE001 — missing tesseract binary, bad image, etc.
        logger.debug("OCR.image_ocr_unavailable | error={error}", error=str(exc))
        return ""


def _extract_image_metadata_text(file_bytes: bytes) -> str:
    """Pull EXIF / PNG text chunks when available (no hard dependency)."""
    fragments: list[str] = []
    try:
        from PIL import Image  # type: ignore[import-not-found]
        from PIL.ExifTags import TAGS  # type: ignore[import-not-found]
    except ImportError:
        return ""

    try:
        image = Image.open(io.BytesIO(file_bytes))
        exif = getattr(image, "getexif", lambda: None)()
        if exif:
            for tag_id, value in exif.items():
                label = TAGS.get(tag_id, str(tag_id))
                if isinstance(value, (str, bytes, int, float)):
                    fragments.append(f"{label}: {_safe_decode(value) if isinstance(value, bytes) else value}")
        info = getattr(image, "info", {}) or {}
        for key, value in info.items():
            if isinstance(value, (str, bytes)):
                fragments.append(
                    f"{key}: {_safe_decode(value) if isinstance(value, bytes) else value}"
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("OCR.image_meta_failed | error={error}", error=str(exc))
        return ""

    return "\n".join(fragments)


def _match_transaction_id(text: str) -> str | None:
    normalized = text.replace("\u00a0", " ")
    for pattern in _TX_LABEL_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(1)

    # Prefer 12-digit then 11 then 10 when only bare sequences exist near Kaspi cues.
    kaspi_context = bool(re.search(r"kaspi|каспи", normalized, re.IGNORECASE))
    candidates = _TX_BARE_DIGIT_PATTERN.findall(normalized)
    if not candidates:
        return None
    if kaspi_context or re.search(r"перевод|транзак", normalized, re.IGNORECASE):
        # Longest first (Kaspi transfer ids are typically 12 digits).
        candidates_sorted = sorted(set(candidates), key=lambda item: (-len(item), item))
        return candidates_sorted[0]
    return None


def _match_amount(text: str) -> Decimal | None:
    normalized = text.replace("\u00a0", " ")
    for pattern in _AMOUNT_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        parsed = _parse_amount_token(match.group(1))
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _parse_amount_token(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace(" ", "").replace("\u00a0", "")
    if not cleaned:
        return None
    # Prefer comma as decimal separator when both appear (EU/KZ style: 15 000,00).
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            cleaned = f"{parts[0]}.{parts[1]}"
        else:
            cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _safe_decode(value: bytes | str) -> str:
    if isinstance(value, str):
        return value
    for encoding in ("utf-8", "cp1251", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="ignore")


def _looks_like_receipt_text(text: str) -> bool:
    if not text or len(text.strip()) < 8:
        return False
    return bool(
        re.search(r"kaspi|каспи|тенге|₸|сумма|перевод|транзак", text, re.IGNORECASE)
    )


def parse_kaspi_receipt_text(text: str) -> KaspiReceiptData:
    """Parse already-extracted receipt text into structured Kaspi fields."""
    raw = (text or "").strip()
    if not raw:
        return KaspiReceiptData(source="empty")
    tx = _match_transaction_id(raw)
    amount = _match_amount(raw)
    return KaspiReceiptData(
        transaction_id=tx,
        amount=amount,
        raw_text=raw[:4000],
        source="text",
    )


def _looks_like_image(file_bytes: bytes) -> bool:
    if len(file_bytes) < 8:
        return False
    return (
        file_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        or file_bytes[:3] == b"\xff\xd8\xff"
        or file_bytes[:4] == b"RIFF"
        or file_bytes[:6] in (b"GIF87a", b"GIF89a")
    )
