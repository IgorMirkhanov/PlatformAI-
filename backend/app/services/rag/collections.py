"""Chroma collection naming + metadata filters for multi-tenant RAG."""

from __future__ import annotations

import re
from typing import Any


def org_collection_name(org_id: str) -> str:
    """Strict tenant isolation: ``org_{org_id}``."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", str(org_id).strip())
    return f"org_{cleaned}"[:128]


def build_org_where_filter(
    *,
    bot_id: str | None = None,
    kb_id: str | None = None,
    document_id: str | None = None,
    allowed_document_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    Payload metadata filter for org-scoped collections.

    Always prefer filtering by ``bot_id`` and/or ``kb_id`` so one org collection
    can host many bots / knowledge bases safely.
    """
    clauses: list[dict[str, Any]] = []
    if bot_id:
        clauses.append({"bot_id": str(bot_id)})
    if kb_id:
        clauses.append({"kb_id": str(kb_id)})
    if document_id:
        clauses.append({"document_id": str(document_id)})
    if allowed_document_ids is not None:
        if len(allowed_document_ids) == 0:
            return None
        clauses.append({"document_id": {"$in": list(allowed_document_ids)}})

    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}
