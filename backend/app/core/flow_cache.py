"""In-memory published-flow cache for the execution engine.

Keeps the latest compiled graph_data per bot_id so webhook / sandbox
runners register freshly published logic without waiting for process restart.

A Redis version stamp is consulted on every ``get`` so multi-worker
deployments drop stale process-local entries after another worker publishes.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class CachedPublishedFlow:
    flow_id: uuid.UUID
    bot_id: uuid.UUID
    title: str
    graph_data: dict[str, Any]
    is_published: bool
    updated_at: datetime
    version: str = "0"


class PublishedFlowCache:
    """Thread-safe process-local cache keyed by bot_id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[uuid.UUID, CachedPublishedFlow] = {}

    def get(self, bot_id: uuid.UUID) -> CachedPublishedFlow | None:
        with self._lock:
            entry = self._entries.get(bot_id)
        if entry is None:
            return None
        try:
            from app.core.redis_client import get_flow_cache_version

            remote = get_flow_cache_version(str(bot_id))
        except Exception:
            remote = None
        # Redis unavailable → trust local (single-process / degraded).
        if remote is None:
            return entry
        if str(entry.version) != str(remote):
            with self._lock:
                self._entries.pop(bot_id, None)
            return None
        return entry

    def set(self, entry: CachedPublishedFlow) -> None:
        with self._lock:
            self._entries[entry.bot_id] = entry

    def invalidate(self, bot_id: uuid.UUID) -> None:
        with self._lock:
            self._entries.pop(bot_id, None)
        try:
            from app.core.redis_client import bump_flow_cache_version

            bump_flow_cache_version(str(bot_id))
        except Exception:
            pass

    def put_from_orm(
        self,
        *,
        flow_id: uuid.UUID,
        bot_id: uuid.UUID,
        title: str,
        graph_data: dict[str, Any],
        is_published: bool,
        updated_at: datetime | None = None,
    ) -> CachedPublishedFlow:
        version = "0"
        try:
            from app.core.redis_client import get_flow_cache_version

            version = get_flow_cache_version(str(bot_id)) or "0"
        except Exception:
            version = "0"
        entry = CachedPublishedFlow(
            flow_id=flow_id,
            bot_id=bot_id,
            title=title,
            graph_data=dict(graph_data) if isinstance(graph_data, dict) else {},
            is_published=is_published,
            updated_at=updated_at or datetime.now(timezone.utc),
            version=str(version),
        )
        self.set(entry)
        return entry


published_flow_cache = PublishedFlowCache()

