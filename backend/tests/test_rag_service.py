"""Unit tests — RAGService with mocked Chroma / document parser."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.rag_service import rag_service


@pytest.mark.asyncio
async def test_rag_ingest_file(monkeypatch):
    bot_id = uuid.uuid4()
    org_id = uuid.uuid4()

    monkeypatch.setattr(
        "app.services.rag_service.extract_text_from_bytes",
        lambda content, filename: "Hello knowledge base content " * 20,
    )

    async def fake_ingest(bot_id_str, text, source_metadata=None):
        return {
            "bot_id": bot_id_str,
            "document_id": str(uuid.uuid4()),
            "collection": f"bot_{bot_id_str}",
            "chunks_stored": 3,
            "file_name": (source_metadata or {}).get("file_name", "x.txt"),
        }

    monkeypatch.setattr(
        "app.services.rag_service.ingest_document_to_chroma",
        fake_ingest,
    )

    summary = await rag_service.ingest_file(
        SimpleNamespace(),  # type: ignore[arg-type]
        bot_id=bot_id,
        organization_id=org_id,
        filename="faq.txt",
        content=b"ignored",
    )
    assert summary["chunk_count"] == 3
    assert summary["character_count"] > 0


@pytest.mark.asyncio
async def test_rag_search_filters_tenant(monkeypatch):
    bot_id = uuid.uuid4()
    org_ok = uuid.uuid4()
    org_other = uuid.uuid4()

    class Hit:
        def __init__(self, text: str, org: str):
            self.text = text
            self.metadata = {"organization_id": org}
            self.score = 0.1

    async def fake_detailed(kb, query, top_k=3):
        return [
            Hit("ok chunk", str(org_ok)),
            Hit("other tenant", str(org_other)),
        ]

    monkeypatch.setattr(
        "app.services.rag_service.similarity_search_detailed",
        fake_detailed,
    )

    hits = await rag_service.search(
        bot_id=bot_id,
        query="hours",
        organization_id=org_ok,
    )
    assert len(hits) == 1
    assert hits[0]["text"] == "ok chunk"
