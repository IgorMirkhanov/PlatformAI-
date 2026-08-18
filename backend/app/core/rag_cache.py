"""In-memory cache for per-bot knowledge-document activation sets.

Used by the RAG retrieval layer so toggles take effect immediately without
re-querying PostgreSQL on every dialog turn, while remaining easy to invalidate.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field


@dataclass(slots=True)
class BotDocumentActivationSnapshot:
    bot_id: uuid.UUID
    active_document_ids: list[str] = field(default_factory=list)
    inactive_document_ids: list[str] = field(default_factory=list)


class RagActivationCache:
    """Thread-safe process-local cache of active / inactive document ID lists."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[uuid.UUID, BotDocumentActivationSnapshot] = {}

    def get(self, bot_id: uuid.UUID) -> BotDocumentActivationSnapshot | None:
        with self._lock:
            return self._entries.get(bot_id)

    def set(self, snapshot: BotDocumentActivationSnapshot) -> None:
        with self._lock:
            self._entries[snapshot.bot_id] = snapshot

    def invalidate(self, bot_id: uuid.UUID) -> None:
        with self._lock:
            self._entries.pop(bot_id, None)

    def put(
        self,
        bot_id: uuid.UUID,
        *,
        active_document_ids: list[str],
        inactive_document_ids: list[str],
    ) -> BotDocumentActivationSnapshot:
        snapshot = BotDocumentActivationSnapshot(
            bot_id=bot_id,
            active_document_ids=list(active_document_ids),
            inactive_document_ids=list(inactive_document_ids),
        )
        self.set(snapshot)
        return snapshot


rag_activation_cache = RagActivationCache()
