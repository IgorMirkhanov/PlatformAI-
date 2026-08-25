"""QA automation: Integration Hub webhook dedup (§3) + CRM rate limits (§5)."""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.integration_hub.rate_limit import (
    BITRIX_CONNECTION_RPS,
    ConnectionRateLimited,
    acquire_bitrix_connection_slot,
    wait_for_connection_slot,
)
from app.services.integration_hub.webhook_dedup import (
    accept_inbound_webhook,
    enqueue_if_needed,
    redis_dedup_key,
)
from app.services.webhook_processor import process_hub_inbound_event


class _FakeRedis:
    """Minimal Redis: SET NX + sliding-window ZSET ops used by hub limiters."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.counters: dict[str, int] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        _ = ex
        with self._lock:
            if nx and key in self.kv:
                return False
            self.kv[key] = value
            return True

    def incr(self, key: str) -> int:
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + 1
            return self.counters[key]

    def expire(self, key: str, ttl: int) -> bool:
        _ = key, ttl
        return True

    def eval(self, script: str, numkeys: int, *args: Any) -> list[float | int]:
        _ = script, numkeys
        key = str(args[0])
        now = float(args[1])
        window = float(args[2])
        limit = int(float(args[3]))
        member = str(args[4])
        with self._lock:
            bucket = self.zsets.setdefault(key, {})
            cutoff = now - window
            for mid, score in list(bucket.items()):
                if score < cutoff:
                    del bucket[mid]
            if len(bucket) >= limit:
                oldest = min(bucket.values()) if bucket else now
                retry_after = max(0.01, window - (now - oldest))
                return [0, len(bucket), retry_after]
            bucket[member] = now
            return [1, len(bucket), 0]


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.get_redis_client",
        lambda: client,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.rate_limit.get_redis_client",
        lambda: client,
    )
    return client


def _connection(*, org_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        provider="bitrix24",
    )


@pytest.mark.asyncio
async def test_duplicate_external_event_id_returns_ok_without_second_side_effect(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second delivery with same external_event_id → side-effects = 1 (no re-enqueue)."""
    connection = _connection()
    ext_id = f"evt-{uuid.uuid4()}"
    enqueued: list[uuid.UUID] = []

    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.enqueue_hub_webhook_job",
        lambda event_id: enqueued.append(event_id),
    )

    inserted_once = {"done": False}

    class _Session:
        async def scalar(self, stmt: Any) -> Any:
            sql = str(stmt)
            if "INSERT" in sql.upper() or "insert" in sql:
                if inserted_once["done"]:
                    return None
                inserted_once["done"] = True
                return uuid.uuid4()
            return None

    db = _Session()
    first = await process_hub_inbound_event(
        db,  # type: ignore[arg-type]
        connection=connection,  # type: ignore[arg-type]
        provider="bitrix24",
        external_event_id=ext_id,
        payload={"event": "ONCRMDEALADD", "entity_id": "1"},
    )
    enqueue_if_needed(first)

    second = await process_hub_inbound_event(
        db,  # type: ignore[arg-type]
        connection=connection,  # type: ignore[arg-type]
        provider="bitrix24",
        external_event_id=ext_id,
        payload={"event": "ONCRMDEALADD", "entity_id": "1"},
    )
    enqueue_if_needed(second)

    assert first.should_enqueue is True
    assert first.is_new is True
    assert second.duplicate is True
    assert second.should_enqueue is False
    assert len(enqueued) == 1
    assert redis_dedup_key("bitrix24", ext_id) in fake_redis.kv


@pytest.mark.asyncio
async def test_workspace_mismatch_marks_dead_letter_without_enqueue(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = uuid.uuid4()
    foreign = uuid.uuid4()
    connection = _connection(org_id=org)
    enqueued: list[uuid.UUID] = []
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.enqueue_hub_webhook_job",
        lambda event_id: enqueued.append(event_id),
    )

    class _Session:
        async def scalar(self, _stmt: Any) -> Any:
            return uuid.uuid4()

    result = await accept_inbound_webhook(
        _Session(),  # type: ignore[arg-type]
        connection=connection,  # type: ignore[arg-type]
        provider="wazzup",
        external_event_id=f"msg-{uuid.uuid4()}",
        payload={"workspace_id": str(foreign), "text": "hi"},
    )
    enqueue_if_needed(result)
    assert result.dead_letter is True
    assert result.should_enqueue is False
    assert enqueued == []
    _ = fake_redis


def test_bitrix24_parallel_calls_respect_two_rps(fake_redis: _FakeRedis) -> None:
    """20 parallel paced Bitrix acquires on one connection_id stay ≤ 2 req/s."""
    connection_id = uuid.uuid4()
    other_id = uuid.uuid4()

    # Isolation: filling A's budget must not block B.
    for _ in range(BITRIX_CONNECTION_RPS):
        acquire_bitrix_connection_slot(connection_id)
    acquire_bitrix_connection_slot(other_id)
    with pytest.raises(ConnectionRateLimited):
        acquire_bitrix_connection_slot(connection_id)

    paced_id = uuid.uuid4()
    stamps: list[float] = []

    def _worker() -> float:
        wait_for_connection_slot(
            paced_id,
            provider="bitrix24",
            limit=BITRIX_CONNECTION_RPS,
            window_seconds=1.0,
            timeout=45.0,
        )
        return time.monotonic()

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_worker) for _ in range(20)]
        for fut in as_completed(futures):
            stamps.append(fut.result())
    elapsed = time.monotonic() - t0
    stamps.sort()

    # 20 calls @ 2/s ⇒ theoretical floor ~9s after the initial burst of 2.
    assert elapsed >= 8.5, f"effective rate too high: 20 calls in {elapsed:.2f}s"
    for i, start in enumerate(stamps):
        in_window = sum(1 for ts in stamps[i:] if ts - start < 1.0)
        assert in_window <= BITRIX_CONNECTION_RPS
    _ = fake_redis
