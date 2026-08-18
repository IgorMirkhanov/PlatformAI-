"""Step 1.5 — LLM Gateway RAG: ingest, similarity search, tenant isolation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from app.models.llm.knowledge import KnowledgeBase, KnowledgeDocument
from app.services.llm.rag_service import (
    KnowledgeBaseNotFoundError,
    RAGService,
    chunk_text,
    cosine_similarity,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self) -> None:
        self.bases: dict[uuid.UUID, KnowledgeBase] = {}
        self.docs: dict[uuid.UUID, KnowledgeDocument] = {}


class FakeSession:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, obj: Any) -> None:
        if isinstance(obj, KnowledgeBase):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            obj.updated_at = getattr(obj, "updated_at", None) or _now()
            self.store.bases[obj.id] = obj
        elif isinstance(obj, KnowledgeDocument):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            obj.chunk_index = int(getattr(obj, "chunk_index", 0) or 0)
            self.store.docs[obj.id] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        if isinstance(obj, KnowledgeBase):
            obj.updated_at = _now()

    async def get(self, model: Any, ident: Any) -> Any:
        if model is KnowledgeBase:
            return self.store.bases.get(ident)
        if model is KnowledgeDocument:
            return self.store.docs.get(ident)
        return None

    async def execute(self, stmt: Any) -> Any:
        rows = self._filter(stmt)

        class _Result:
            def scalars(self_inner) -> Any:
                class _S:
                    def all(self_s) -> list[Any]:
                        return list(rows)

                return _S()

            def scalar_one_or_none(self_inner) -> Any:
                return rows[0] if rows else None

        return _Result()

    def _filter(self, stmt: Any) -> list[Any]:
        try:
            compiled = stmt.compile(compile_kwargs={"render_postcompile": True})
            sql = str(compiled).lower()
            params = dict(compiled.params or {})
        except Exception:
            sql = str(stmt).lower()
            params = {}

        values = list(params.values())
        if "llm_knowledge_documents" in sql or "knowledge_base_id" in sql:
            rows: list[Any] = list(self.store.docs.values())
            base_ids = [v for v in values if isinstance(v, uuid.UUID) and v in self.store.bases]
            # also match ids that only exist as knowledge_base_id on docs
            kb_ids = [v for v in values if isinstance(v, uuid.UUID)]
            if kb_ids:
                oid = kb_ids[0]
                rows = [r for r in rows if r.knowledge_base_id == oid]
            return rows

        rows = list(self.store.bases.values())
        org_ids = [v for v in values if isinstance(v, uuid.UUID)]
        names = [v for v in values if isinstance(v, str)]
        if org_ids:
            rows = [r for r in rows if r.organization_id == org_ids[0]]
        if names and "name" in sql:
            rows = [r for r in rows if r.name == names[0]]
        # select(KnowledgeBase.id) conflict checks return id scalars
        if "llm_knowledge_bases.id" in sql or sql.strip().startswith("select") and "id" in sql:
            if names and org_ids:
                matched = [
                    r.id
                    for r in self.store.bases.values()
                    if r.organization_id == org_ids[0] and r.name == names[0]
                ]
                return matched  # type: ignore[return-value]
        rows.sort(key=lambda r: r.name)
        return rows


async def _toy_embed(texts: list[str]) -> list[list[float]]:
    """
    Deterministic 3-D embeddings for tests.

    Fruits → near [1,0,0]; cars → near [0,1,0]; other → [0,0,1].
    """
    out: list[list[float]] = []
    for text in texts:
        lower = text.lower()
        if any(w in lower for w in ("яблок", "apple", "фрукт", "fruit")):
            out.append([1.0, 0.0, 0.0])
        elif any(w in lower for w in ("машин", "car", "авто", "vehicle")):
            out.append([0.0, 1.0, 0.0])
        else:
            out.append([0.0, 0.0, 1.0])
    return out


def test_chunk_text_overlap() -> None:
    text = "a" * 1200
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) >= 2
    assert all(len(c) <= 500 for c in chunks)


def test_cosine_similarity_identical() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_create_base_and_ingest_stores_chunks() -> None:
    store = Store()
    db = FakeSession(store)
    org_id = uuid.uuid4()
    service = RAGService(embed_fn=_toy_embed)

    base = await service.create_knowledge_base(
        db,  # type: ignore[arg-type]
        org_id,
        name="База знаний техподдержки",
    )
    assert base.organization_id == org_id

    result = await service.ingest_document(
        db,  # type: ignore[arg-type]
        org_id,
        base.id,
        file_name="faq.txt",
        text=(
            "Яблоки — полезный фрукт. " * 40
            + "Машины требуют регулярного ТО. " * 40
        ),
        chunk_size=200,
        overlap=20,
    )
    assert result["chunks_stored"] >= 2
    assert len(store.docs) == result["chunks_stored"]
    assert all(len(d.embedding) == 3 for d in store.docs.values())
    assert all(d.file_name == "faq.txt" for d in store.docs.values())


@pytest.mark.asyncio
async def test_similarity_search_returns_relevant_chunk() -> None:
    store = Store()
    db = FakeSession(store)
    org_id = uuid.uuid4()
    service = RAGService(embed_fn=_toy_embed)

    base = await service.create_knowledge_base(db, org_id, name="kb")  # type: ignore[arg-type]
    await service.ingest_document(
        db,  # type: ignore[arg-type]
        org_id,
        base.id,
        file_name="mixed.txt",
        text="Информация про яблоки и фрукты.\n\nИнформация про машины и авто.",
        chunk_size=80,
        overlap=0,
    )

    hits = await service.similarity_search(
        db,  # type: ignore[arg-type]
        org_id,
        base.id,
        "Расскажи про apple fruit",
        top_k=1,
    )
    assert len(hits) == 1
    assert "яблок" in hits[0]["content"].lower() or "фрукт" in hits[0]["content"].lower()
    assert hits[0]["score"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_tenant_isolation_org_a_cannot_access_org_b_base() -> None:
    store = Store()
    db = FakeSession(store)
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    service = RAGService(embed_fn=_toy_embed)

    base_b = await service.create_knowledge_base(
        db,  # type: ignore[arg-type]
        org_b,
        name="secret_kb",
    )
    await service.ingest_document(
        db,  # type: ignore[arg-type]
        org_b,
        base_b.id,
        file_name="b.txt",
        text="Org B confidential apple fruit content for embeddings.",
        chunk_size=200,
        overlap=0,
    )

    listed_a = await service.list_knowledge_bases(db, org_a)  # type: ignore[arg-type]
    assert listed_a == []

    with pytest.raises(KnowledgeBaseNotFoundError):
        await service.get_knowledge_base(db, base_b.id, org_a)  # type: ignore[arg-type]

    with pytest.raises(KnowledgeBaseNotFoundError):
        await service.similarity_search(
            db,  # type: ignore[arg-type]
            org_a,
            base_b.id,
            "apple",
        )
