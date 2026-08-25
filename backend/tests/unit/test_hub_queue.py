"""Integration Hub Celery queue: inbound verify→received→job, consumer dedup, outbound RL."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.integration_hub import (
    AgentActionStatus,
    IntegrationAgentAction,
    WebhookEventStatus,
)
from app.services.integration_hub.crm_adapter import CRMContact
from app.services.integration_hub.queue import (
    canonical_action_type,
    claim_webhook_event,
    enqueue_adapter_action,
    enqueue_hub_webhook_job,
    normalize_hub_event,
    record_received_event,
    release_outbound_lock,
    sanitize_payload,
    serialize_action_result,
    try_acquire_outbound_lock,
)
from app.services.integration_hub.rate_limit import ConnectionRateLimited
from app.tasks.hub_queue_tasks import (
    _execute_adapter_action,
    execute_hub_adapter_action_task,
)


def test_sanitize_payload_redacts_tokens() -> None:
    cleaned = sanitize_payload(
        {
            "auth": {"application_token": "secret", "member_id": "m1", "access_token": "at"},
            "event": "ONCRMDEALADD",
        }
    )
    assert cleaned["auth"]["application_token"] == "[redacted]"
    assert cleaned["auth"]["access_token"] == "[redacted]"
    assert cleaned["auth"]["member_id"] == "m1"
    assert cleaned["event"] == "ONCRMDEALADD"


def test_canonical_action_aliases() -> None:
    assert canonical_action_type("createContact") == "create_contact"
    assert canonical_action_type("sendMessage") == "send_message"
    assert canonical_action_type("create_deal") == "create_deal"


def test_serialize_dataclass_contact() -> None:
    payload = serialize_action_result(CRMContact(id="77", name="Ada", phone="+1"))
    assert payload["id"] == "77"
    assert payload["name"] == "Ada"


def test_normalize_resolves_workspace_and_agent() -> None:
    workspace = uuid.uuid4()
    agent = uuid.uuid4()
    connection = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=workspace,
        bot_id=agent,
    )
    event = SimpleNamespace(
        provider="wazzup",
        external_event_id="m-1",
        payload_json={"type": "message.received", "text": "hi"},
    )
    normalized = normalize_hub_event(event=event, connection=connection)
    assert normalized["workspace_id"] == str(workspace)
    assert normalized["agent_id"] == str(agent)
    assert normalized["type"] == "message.received"


@pytest.mark.asyncio
async def test_record_received_then_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    event_id = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=event_id)
    connection = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4())
    queued: list[object] = []
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.process_hub_webhook_event_task.apply_async",
        lambda *a, **k: queued.append((k.get("args") or list(a))[0]),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.claim_webhook_dedup_key",
        lambda *a, **k: True,
    )
    inserted = await record_received_event(
        db,
        connection=connection,  # type: ignore[arg-type]
        provider="bitrix24",
        external_event_id=f"ext-{uuid.uuid4()}",
        payload={"event": "ONCRMDEALADD", "auth": {"application_token": "secret"}},
    )
    assert inserted == event_id
    enqueue_hub_webhook_job(event_id)
    assert queued == [str(event_id)]


@pytest.mark.asyncio
async def test_claim_skips_already_processed() -> None:
    event = SimpleNamespace(
        id=uuid.uuid4(),
        status=WebhookEventStatus.PROCESSED.value,
        provider="wazzup",
        external_event_id="m-1",
    )
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=event)
    outcome, row = await claim_webhook_event(db, event.id)
    assert outcome == "duplicate"
    assert row is event


@pytest.mark.asyncio
async def test_claim_marks_received_as_processing() -> None:
    event = SimpleNamespace(
        id=uuid.uuid4(),
        status=WebhookEventStatus.RECEIVED.value,
        provider="wazzup",
        external_event_id="m-1",
    )
    db = AsyncMock()
    calls = {"n": 0}

    async def scalar_side_effect(_stmt):
        calls["n"] += 1
        if calls["n"] == 1:
            return event
        return None

    db.scalar = AsyncMock(side_effect=scalar_side_effect)
    outcome, row = await claim_webhook_event(db, event.id)
    assert outcome == "claimed"
    assert row.status == WebhookEventStatus.PROCESSING.value


def test_outbound_lock_groups_by_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, tuple[str, int | None]] = {}

    class _Redis:
        def set(self, key, value, nx=False, ex=None):
            if nx and key in store:
                return False
            assert ex is not None and int(ex) >= 15
            store[key] = (value, ex)
            return True

        def delete(self, key):
            store.pop(key, None)

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
    assert store[f"ihub:lock:outbound:{cid}"][1] == 90
    assert try_acquire_outbound_lock(cid) is False
    release_outbound_lock(cid)
    assert try_acquire_outbound_lock(cid) is True


@pytest.mark.asyncio
async def test_claim_reclaims_error_for_retry() -> None:
    event = SimpleNamespace(
        id=uuid.uuid4(),
        status=WebhookEventStatus.ERROR.value,
        provider="wazzup",
        external_event_id="m-1",
        created_at=None,
        error="boom",
    )
    db = AsyncMock()
    calls = {"n": 0}

    async def scalar_side_effect(_stmt):
        calls["n"] += 1
        if calls["n"] == 1:
            return event
        return None

    db.scalar = AsyncMock(side_effect=scalar_side_effect)
    outcome, row = await claim_webhook_event(db, event.id)
    assert outcome == "claimed"
    assert row.status == WebhookEventStatus.PROCESSING.value


@pytest.mark.asyncio
async def test_claim_skips_dead_letter() -> None:
    event = SimpleNamespace(
        id=uuid.uuid4(),
        status=WebhookEventStatus.DEAD_LETTER.value,
        provider="wazzup",
        external_event_id="m-1",
    )
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=event)
    outcome, row = await claim_webhook_event(db, event.id)
    assert outcome == "dead_letter"
    assert row is event


def test_webhook_task_dead_letters_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.tasks.hub_queue_tasks import process_hub_webhook_event_task

    dead: list[tuple[str, str]] = []

    async def boom(_event_id: str):
        raise RuntimeError("normalize failed")

    async def dl(event_id: str, error: str):
        dead.append((event_id, error))

    monkeypatch.setattr("app.tasks.hub_queue_tasks._consume_webhook_event", boom)
    monkeypatch.setattr("app.tasks.hub_queue_tasks._dead_letter_webhook", dl)
    monkeypatch.setattr("app.tasks.hub_queue_tasks._hub_webhook_max_retries", lambda: 0)
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.run_celery_async",
        lambda coro: asyncio.run(coro),
    )

    event_id = str(uuid.uuid4())
    process_hub_webhook_event_task.push_request(retries=0)
    try:
        result = process_hub_webhook_event_task.run(event_id)
    finally:
        process_hub_webhook_event_task.pop_request()
    assert result == {"status": "dead_letter", "event_id": event_id}
    assert dead and dead[0][0] == event_id
    assert "normalize failed" in dead[0][1]


def test_execute_task_retries_when_connection_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.try_acquire_outbound_lock",
        lambda *_a, **_k: False,
    )

    def _retry(*_a, **_k):
        raise RuntimeError("retried")

    monkeypatch.setattr(execute_hub_adapter_action_task, "retry", _retry)
    with pytest.raises(RuntimeError, match="retried"):
        execute_hub_adapter_action_task.run("cid", "create_contact", {"name": "Ada"})


@pytest.mark.asyncio
async def test_adapter_action_logs_request_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        bot_id=uuid.uuid4(),
        provider="bitrix24",
        status="connected",
    )
    logged: list[IntegrationAgentAction] = []

    class _Session:
        async def get(self, _model, _id):
            return connection

        def add(self, row):
            logged.append(row)

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def scalar(self, _stmt):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Factory:
        def __call__(self):
            return _Session()

    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.async_session_factory",
        _Factory(),
    )
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.secrets_from_connection_with_vault",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks._call_adapter",
        AsyncMock(return_value=CRMContact(id="501", name="Ada")),
    )
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.record_hub_usage",
        AsyncMock(return_value=None),
    )
    result = await _execute_adapter_action(
        str(connection.id),
        "createContact",
        {"name": "Ada", "phone": "+1", "access_token": "should-not-leak"},
    )
    assert result.id == "501"
    assert len(logged) == 1
    row = logged[0]
    assert row.action_type == "create_contact"
    assert row.status == AgentActionStatus.OK.value
    assert row.request_payload["name"] == "Ada"
    assert row.request_payload["access_token"] == "[redacted]"
    assert row.response_payload["id"] == "501"


@pytest.mark.asyncio
async def test_adapter_action_rate_limit_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        bot_id=None,
        provider="bitrix24",
        status="connected",
    )
    logged: list[IntegrationAgentAction] = []

    class _Session:
        async def get(self, _model, _id):
            return connection

        def add(self, row):
            logged.append(row)

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Factory:
        def __call__(self):
            return _Session()

    monkeypatch.setattr("app.tasks.hub_queue_tasks.async_session_factory", _Factory())
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.secrets_from_connection_with_vault",
        AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks._call_adapter",
        AsyncMock(side_effect=ConnectionRateLimited("slow down")),
    )
    with pytest.raises(ConnectionRateLimited):
        await _execute_adapter_action(str(connection.id), "create_contact", {"name": "Ada"})
    assert logged[0].status == AgentActionStatus.RATE_LIMITED.value


@pytest.mark.asyncio
async def test_consume_duplicate_does_not_dispatch_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks.hub_queue_tasks import _consume_webhook_event

    event = SimpleNamespace(id=uuid.uuid4(), status=WebhookEventStatus.PROCESSED.value)

    class _Session:
        async def scalar(self, _stmt):
            return event

        async def commit(self):
            return None

        async def get(self, *_a, **_k):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Factory:
        def __call__(self):
            return _Session()

    dispatched = []
    monkeypatch.setattr("app.tasks.hub_queue_tasks.async_session_factory", _Factory())
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks._dispatch_normalized",
        AsyncMock(side_effect=lambda **k: dispatched.append(k) or {}),
    )
    result = await _consume_webhook_event(str(event.id))
    assert result["status"] == "duplicate"
    assert dispatched == []


def test_enqueue_adapter_action_routes_to_outbound_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Result:
        id = "task-1"

        def get(self, timeout=None):
            return {"id": "9"}

    def apply_async(*_a, **kwargs):
        captured.update(kwargs)
        return _Result()

    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.execute_hub_adapter_action_task.apply_async",
        apply_async,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.queue.assert_connection_allows_outbound_sync",
        lambda _cid: None,
    )
    out = enqueue_adapter_action(uuid.uuid4(), "sendMessage", {"chat_id": "1", "text": "hi"})
    assert out["queued"] is True
    assert captured["args"][1] == "sendMessage"
    waited = enqueue_adapter_action(
        uuid.uuid4(), "createContact", {"name": "Ada"}, wait=True
    )
    assert waited == {"id": "9"}
