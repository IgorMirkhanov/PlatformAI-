"""RAG package — tenant-isolated collections + async ingestion helpers."""

from app.services.rag.collections import (
    build_org_where_filter,
    org_collection_name,
)

__all__ = [
    "build_org_where_filter",
    "org_collection_name",
    "KnowledgeIngestionService",
    "knowledge_ingestion_service",
]


def __getattr__(name: str):
    # Lazy imports avoid circular dependency with vector_db ↔ knowledge_base_service.
    if name in {"KnowledgeIngestionService", "knowledge_ingestion_service"}:
        from app.services.rag import ingestion as _ingestion

        return getattr(_ingestion, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
