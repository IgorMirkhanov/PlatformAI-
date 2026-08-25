"""QA automation: Integration Hub §6 outbound locks + §8 billing usage bridge."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.integration_hub import IntegrationUsageEvent
from app.models.saas_metering import UsageMetricType
from app.services.integration_hub.hub_usage import (
    build_hub_action_idempotency_key,
    record_hub_usage,
)
from app.services.integration_hub.queue import (
    outbound_job_timeout_seconds,
    outbound_lock_key,
    outbound_lock_ttl,
    release_outbound_lock,
    try_acquire_outbound_lock,
)


def _connection(*, provider: str = "bitrix24") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        bot_id=None,
        provider=provider,
    )


def test_outbound_lock_key_matches_checklist_prefix() -> None:
    cid = str(uuid.uuid4())
    assert outbound_lock_key(cid) == f"ihub:lock:outbound:{cid}"


def test_outbound_job_timeout_strictly_below_lock_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.integration_hub.queue.settings.HUB_OUTBOUND_LOCK_TTL_SECONDS",
        90,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.queue.settings.HUB_OUTBOUND_JOB_TIMEOUT_SECONDS",
        60,
    )
    ttl = outbound_lock_ttl()
    timeout = outbound_job_timeout_seconds()
    assert ttl == 90
    assert timeout < ttl
    assert timeout == 60.0


def test_outbound_job_timeout_clamped_under_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Misconfigured job timeout >= TTL is forced below lock expiry."""
    monkeypatch.setattr(
        "app.services.integration_hub.queue.settings.HUB_OUTBOUND_LOCK_TTL_SECONDS",
        30,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.queue.settings.HUB_OUTBOUND_JOB_TIMEOUT_SECONDS",
        90,
    )
    assert outbound_job_timeout_seconds() == 25.0  # ttl - 5


def test_kill9_unlock_relies_on_redis_ttl_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker crash skips release_outbound_lock; Redis EX reclaim is the unlock path."""
    store: dict[str, tuple[str, int]] = {}

    class _Redis:
        def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
            if nx and key in store:
                return False
            assert ex is not None and int(ex) >= 15
            store[key] = (value, int(ex))
            return True

        def delete(self, key: str) -> int:
            return 1 if store.pop(key, None) is not None else 0

    monkeypatch.setattr(
        "app.services.integration_hub.queue.get_redis_client",
        lambda: _Redis(),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.queue.outbound_lock_ttl",
        lambda: 90,
    )
    cid = str(uuid.uuid4())
    assert try_acquire_outbound_lock(cid) is True
    key = outbound_lock_key(cid)
    assert key in store and store[key][1] == 90
    # Simulate kill -9: no release_outbound_lock call — peer still blocked.
    assert try_acquire_outbound_lock(cid) is False
    # After TTL expiry (simulated), connection_id is free again without manual cleanup.
    del store[key]
    assert try_acquire_outbound_lock(cid) is True
    release_outbound_lock(cid)


@pytest.mark.asyncio
async def test_record_hub_usage_dual_writes_integration_and_billing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Atomic bridge: integration_usage_events + usage_events (billing) with source=integration_hub."""
    connection = _connection(provider="wazzup")
    actor_id = uuid.uuid4()
    inserted_id = uuid.uuid4()
    billing_calls: list[dict[str, Any]] = []
    key = build_hub_action_idempotency_key(
        connection_id=connection.id,
        action_type="send_message",
        action_id="msg-action-1",
    )
    assert key is not None

    hub_row = IntegrationUsageEvent(
        id=inserted_id,
        connection_id=connection.id,
        organization_id=connection.organization_id,
        metric="wazzup_outbound",
        quantity=1,
        idempotency_key=key,
    )

    scalar_queue: list[Any] = [
        None,  # existing hub row?
        inserted_id,  # INSERT … RETURNING
        actor_id,  # billing actor (OWNER)
        None,  # prior billing usage_events?
    ]

    db = MagicMock()
    db.scalar = AsyncMock(side_effect=scalar_queue)
    db.get = AsyncMock(return_value=hub_row)

    async def _debit(_db: Any, **kwargs: Any) -> SimpleNamespace:
        billing_calls.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(
        "app.services.integration_hub.hub_usage.usage_service.record_and_debit",
        _debit,
    )

    row = await record_hub_usage(
        db,
        connection=connection,
        metric="wazzup_outbound",
        quantity=1,
        idempotency_key=key,
        meta={"action_type": "send_message", "action_id": "msg-action-1"},
    )

    assert row is hub_row
    assert len(billing_calls) == 1
    call = billing_calls[0]
    assert call["organization_id"] == connection.organization_id
    assert call["metric_type"] == UsageMetricType.MESSAGE_OUT
    assert call["debit_wallet"] is False
    assert call["meta"]["source"] == "integration_hub"
    assert call["meta"]["idempotency_key"] == key
    assert call["meta"]["billing_usage_events"] is True
    assert db.scalar.await_count == 4
    db.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_retry_does_not_duplicate_billing_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Celery retry of the same CRM action_id must not create a second billing meter row."""
    connection = _connection(provider="bitrix24")
    key = build_hub_action_idempotency_key(
        connection_id=connection.id,
        action_type="create_contact",
        action_id="crm-action-42",
    )
    existing = IntegrationUsageEvent(
        id=uuid.uuid4(),
        connection_id=connection.id,
        organization_id=connection.organization_id,
        metric="bitrix24_rest",
        quantity=1,
        idempotency_key=key,
    )
    billing_calls: list[dict[str, Any]] = []

    db = MagicMock()
    db.scalar = AsyncMock(return_value=existing)
    db.get = AsyncMock()

    async def _debit(_db: Any, **kwargs: Any) -> SimpleNamespace:
        billing_calls.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(
        "app.services.integration_hub.hub_usage.usage_service.record_and_debit",
        _debit,
    )

    # Simulated job retry after a prior successful meter write:
    again = await record_hub_usage(
        db,
        connection=connection,
        metric="bitrix24_rest",
        quantity=1,
        idempotency_key=key,
        meta={"action_type": "create_contact", "action_id": "crm-action-42"},
    )
    assert again is None
    assert billing_calls == []
    db.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbound_soft_timeout_below_lock_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks.hub_queue_tasks import _execute_adapter_action_bounded

    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.outbound_job_timeout_seconds",
        lambda: 0.05,
    )

    async def _slow(*_a: Any, **_k: Any) -> str:
        await asyncio.sleep(1.0)
        return "ok"

    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks._execute_adapter_action",
        _slow,
    )
    with pytest.raises(TimeoutError, match="soft timeout"):
        await _execute_adapter_action_bounded(
            str(uuid.uuid4()),
            "create_contact",
            {"action_id": "a-1"},
            celery_task_id="task-1",
        )
