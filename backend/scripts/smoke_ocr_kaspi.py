"""Smoke checks for Kaspi receipt OCR parsing (no DB required)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ocr_service import extract_kaspi_receipt_data


def main() -> None:
    sample = (
        "Kaspi Gold\n"
        "Перевод выполнен\n"
        "Номер перевода: 123456789012\n"
        "Сумма: 15 000 ₸\n"
        "Получатель: MP.AI\n"
    ).encode("utf-8")

    parsed = extract_kaspi_receipt_data(sample, "kaspi-receipt.txt")
    assert parsed is not None
    assert parsed.transaction_id == "123456789012"
    assert parsed.amount == Decimal("15000.00")
    assert parsed.is_complete

    garbage = extract_kaspi_receipt_data(b"\x00\x01\xffnot-an-image", "broken.png")
    assert garbage is None or not garbage.is_complete

    empty = extract_kaspi_receipt_data(b"", "empty.pdf")
    assert empty is None

    print("ocr_smoke_ok", parsed.transaction_id, parsed.amount)


if __name__ == "__main__":
    main()
