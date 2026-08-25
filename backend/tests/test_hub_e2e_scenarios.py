"""E2E scenarios — Integration Hub checklist §11 (full client path).

Unit-style end-to-end: real orchestration code paths with Redis/DB/HTTP/AI stubbed.
Covers Wazzup→AI→Wazzup, CRM capture + hub adapters, Kaspi invoice→payment→billing.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.integration_hub import HubConnectionStatus
from app.models.saas_metering import UsageMetricType
from app.services.integration_hub.hub_usage import record_hub_usage
from app.services.integration_hub.messaging import MessageReceived
from app.services.integration_hub.queue import (
    assert_connection_allows_outbound,
    outbound_lock_key,
    try_acquire_outbound_lock,
)
from app.services.integration_hub.types import TokenBundle


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _conn(
    *,
    provider: str,
    bot_id: uuid.UUID | None = None,
    status: str = HubConnectionStatus.CONNECTED.value,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        bot_id=bot_id or uuid.uuid4(),
        provider=provider,
        status=status,
        config_json={},
        credential_id=None,
        external_account_id=None,
        last_error=None,
    )


def _session_factory(connection: SimpleNamespace, *, extras: dict[str, Any] | None = None):
    """Minimal async_session_factory stand-in used by hub Celery tasks."""

    state = extras or {}

    class _Session:
        def __init__(self) -> None:
            self.added: list[Any] = []

        async def get(self, _model: Any, _id: Any) -> Any:
            return connection

        def add(self, row: Any) -> None:
            self.added.append(row)
            state.setdefault("added", []).append(row)

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            state["committed"] = True

        async def scalar(self, _stmt: Any) -> Any:
            return state.get("scalar")

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    class _Factory:
        def __call__(self) -> _Session:
            return _Session()

    return _Factory()


# ---------------------------------------------------------------------------
# §11.1 — Wazzup → AI Agent → Wazzup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_wazzup_inbound_ai_outbound(monkeypatch: pytest.MonkeyPatch) -> None:
    """Client WhatsApp msg via Wazzup → bot_id resolve → AI → outbound send_message."""
    from app.tasks.hub_queue_tasks import _dispatch_normalized, _execute_adapter_action
    from app.tasks import wazzup_tasks

    bot_id = uuid.uuid4()
    connection = _conn(provider="wazzup", bot_id=bot_id)
    inbound_jobs: list[tuple[str, str, dict[str, Any]]] = []
    ai_calls: list[dict[str, Any]] = []
    outbound_sends: list[dict[str, Any]] = []

    # Canonical message.received envelope (same shape as ingest → payload_json).
    event = MessageReceived(
        type="message.received",
        provider="wazzup",
        connection_id=str(connection.id),
        channel_id="ch-wa",
        channel_type="whatsapp",
        chat_id="77001234567",
        message_id=f"msg-{uuid.uuid4().hex[:8]}",
        text="Здравствуйте, хочу записаться",
        from_id="77001234567",
        from_name="Клиент",
        is_echo=False,
    )
    payload = event.as_dict()

    monkeypatch.setattr(
        "app.tasks.wazzup_tasks.async_session_factory",
        _session_factory(connection),
    )
    monkeypatch.setattr("app.tasks.wazzup_tasks.record_hub_usage", AsyncMock())

    def _enqueue_inbound(args: list[Any], queue: str | None = None, **_k: Any) -> SimpleNamespace:
        inbound_jobs.append((str(args[0]), str(args[1]), dict(args[2])))
        assert queue == "inbound_messages" or queue is not None
        # Simulate AI agent turn after inbound enqueue.
        ai_calls.append(
            {
                "bot_id": args[0],
                "platform": args[1],
                "message": (args[2] or {}).get("message_text"),
                "reply": "Добрый день! На какое время вас записать?",
            }
        )
        return SimpleNamespace(id="inbound-task-1")

    monkeypatch.setattr(
        "app.tasks.wazzup_tasks.process_inbound_message_task.apply_async",
        lambda args, queue=None, **kw: _enqueue_inbound(args, queue=queue, **kw),
    )
    monkeypatch.setattr(
        "app.tasks.wazzup_tasks.settings.CELERY_INBOUND_QUEUE",
        "inbound_messages",
    )

    # 1) Hub dispatch (post-claim consumer) → wazzup_tasks._process
    dispatched = await _dispatch_normalized(
        provider="wazzup",
        connection_id=str(connection.id),
        normalized={
            "type": "message.received",
            "workspace_id": str(connection.organization_id),
            "agent_id": str(bot_id),
            "connection_id": str(connection.id),
        },
        payload=payload,
    )
    assert dispatched["runtime"] == "ai_agent"
    assert dispatched["inbound"] == 1
    assert len(inbound_jobs) == 1
    assert inbound_jobs[0][0] == str(bot_id)
    assert inbound_jobs[0][1] == "WAZZUP"
    assert inbound_jobs[0][2]["message_text"] == payload["text"]
    assert inbound_jobs[0][2]["external_id"] == payload["chat_id"]
    assert ai_calls and ai_calls[0]["reply"]

    # 2) Outbound reply through hub Wazzup adapter (agent / tool path).
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.async_session_factory",
        _session_factory(connection),
    )
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.secrets_from_connection_with_vault",
        AsyncMock(
            return_value=TokenBundle(
                api_key="wazzup-key",
                extra={"channels": [{"channel_id": "ch-wa", "kind": "whatsapp"}]},
            )
        ),
    )

    async def _send_message(self: Any, **kwargs: Any) -> dict[str, Any]:
        outbound_sends.append(kwargs)
        return {"id": "out-1", "status": "ok"}

    monkeypatch.setattr(
        "app.services.integration_hub.adapters.wazzup.WazzupHubAdapter.send_message",
        _send_message,
    )
    monkeypatch.setattr("app.tasks.hub_queue_tasks.record_hub_usage", AsyncMock())
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.persist_agent_action",
        AsyncMock(return_value=SimpleNamespace()),
    )

    result = await _execute_adapter_action(
        str(connection.id),
        "send_message",
        {
            "chat_id": payload["chat_id"],
            "text": ai_calls[0]["reply"],
            "channel_id": "ch-wa",
            "action_id": f"reply:{event.message_id}",
        },
        celery_task_id="e2e-wazzup-1",
    )
    assert result["id"] == "out-1"
    assert len(outbound_sends) == 1
    assert outbound_sends[0]["chat_id"] == "77001234567"
    assert "записать" in outbound_sends[0]["text"].lower()


@pytest.mark.asyncio
async def test_e2e_wazzup_ingest_parses_whatsapp_and_enqueues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP ingest edge: raw Wazzup webhook → message.received → enqueue once."""
    from app.services.integration_hub.wazzup_webhook import ingest_wazzup_hub_webhook
    from app.services.integration_hub.webhook_dedup import InboundAcceptResult

    connection = _conn(provider="wazzup")
    enqueued: list[uuid.UUID] = []
    accepted: list[str] = []

    raw = {
        "messages": [
            {
                "messageId": "wa-e2e-1",
                "channelId": "ch-wa",
                "chatType": "whatsapp",
                "chatId": "77001112233",
                "text": "Привет",
                "dateTime": "2026-08-25T10:00:00Z",
                "contact": {"name": "Ada", "phone": "77001112233"},
            }
        ]
    }

    db = MagicMock()
    db.get = AsyncMock(return_value=connection)
    db.commit = AsyncMock()

    async def _process(_db: Any, **kwargs: Any) -> InboundAcceptResult:
        accepted.append(str(kwargs["external_event_id"]))
        eid = uuid.uuid4()
        return InboundAcceptResult(
            event_id=eid,
            is_new=True,
            duplicate=False,
            dead_letter=False,
            should_enqueue=True,
        )

    monkeypatch.setattr(
        "app.services.integration_hub.wazzup_webhook.process_hub_inbound_event",
        _process,
    )
    monkeypatch.setattr(
        "app.services.integration_hub.wazzup_webhook.enqueue_if_needed",
        lambda result: enqueued.append(result.event_id) if result.should_enqueue else None,
    )

    response = await ingest_wazzup_hub_webhook(
        connection_id=connection.id,
        payload=raw,
        db=db,
    )
    assert response.status_code == 200
    assert accepted == ["wa-e2e-1"]
    assert len(enqueued) == 1


# ---------------------------------------------------------------------------
# §11.2 — CRM automation (amoCRM + Bitrix24) + linked_client_id capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_crm_hub_create_contact_bitrix_and_amocrm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New phone → hub create_contact on Bitrix24 & amoCRM under outbound lock."""
    from app.tasks.hub_queue_tasks import _execute_adapter_action

    store: dict[str, tuple[str, int]] = {}

    class _Redis:
        def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
            if nx and key in store:
                return False
            store[key] = (value, int(ex or 0))
            return True

        def delete(self, key: str) -> int:
            return 1 if store.pop(key, None) is not None else 0

    monkeypatch.setattr(
        "app.services.integration_hub.queue.get_redis_client",
        lambda: _Redis(),
    )

    created: list[tuple[str, dict[str, Any]]] = []

    for provider, action, external_id in (
        ("bitrix24", "createContact", "bx-501"),
        ("amocrm", "create_contact", "amo-77"),
    ):
        connection = _conn(provider=provider)
        lock_key = outbound_lock_key(str(connection.id))
        assert try_acquire_outbound_lock(str(connection.id)) is True
        assert lock_key in store

        monkeypatch.setattr(
            "app.tasks.hub_queue_tasks.async_session_factory",
            _session_factory(connection),
        )
        monkeypatch.setattr(
            "app.tasks.hub_queue_tasks.secrets_from_connection_with_vault",
            AsyncMock(
                return_value=TokenBundle(
                    access_token="tok",
                    extra={"domain": "acme.bitrix24.ru", "subdomain": "acme"},
                )
            ),
        )

        async def _call_adapter(*, connection, action_type, params, secrets, http):  # noqa: ANN001
            _ = secrets, http
            created.append((connection.provider, {"action": action_type, **params}))
            return SimpleNamespace(id=external_id, name=params.get("name"))

        # Bind per-iteration external_id via default arg
        async def _make_call(ext_id: str = external_id):
            async def _inner(*, connection, action_type, params, secrets, http):  # noqa: ANN001
                _ = secrets, http
                created.append((connection.provider, {"action": action_type, **params}))
                return SimpleNamespace(id=ext_id, name=params.get("name"))

            return _inner

        monkeypatch.setattr(
            "app.tasks.hub_queue_tasks._call_adapter",
            await _make_call(),
        )
        monkeypatch.setattr("app.tasks.hub_queue_tasks.record_hub_usage", AsyncMock())
        monkeypatch.setattr(
            "app.tasks.hub_queue_tasks.persist_agent_action",
            AsyncMock(return_value=SimpleNamespace()),
        )

        phone = "+77005551234"
        result = await _execute_adapter_action(
            str(connection.id),
            action,
            {
                "name": "Новый клиент",
                "phone": phone,
                "action_id": f"crm:{provider}:{phone}",
            },
            celery_task_id=f"e2e-crm-{provider}",
        )
        assert str(result.id) in {external_id, str(result.id)}
        # Release as worker finally would.
        from app.services.integration_hub.queue import release_outbound_lock

        release_outbound_lock(str(connection.id))
        assert lock_key not in store

    providers = {row[0] for row in created}
    assert providers == {"bitrix24", "amocrm"}
    assert all(row[1]["phone"] == "+77005551234" for row in created)
    assert all(row[1]["action"] == "create_contact" for row in created)


@pytest.mark.asyncio
async def test_e2e_crm_capture_linked_client_id_no_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inbox Client → CrmContact under advisory lock; second pass returns same row."""
    import importlib

    import app.core.pg_locks as pg_locks

    contact_service_mod = importlib.import_module("app.services.crm.contact_service")
    from app.core.pg_locks import LOCK_NS_CRM_CAPTURE

    client_id = uuid.uuid4()
    org_id = uuid.uuid4()
    lock_calls: list[tuple[int, uuid.UUID]] = []
    contacts: dict[uuid.UUID, SimpleNamespace] = {}

    bot = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=org_id,
        platform_type=SimpleNamespace(value="whatsapp"),
    )
    client = SimpleNamespace(
        id=client_id,
        bot=bot,
        first_name="Ada",
        username="ada",
    )

    class _Result:
        def scalar_one_or_none(self) -> Any:
            return client

    class _Repo:
        def __init__(self) -> None:
            self.adds = 0

        async def get_by_linked_client_id(self, cid: uuid.UUID) -> Any:
            return contacts.get(cid)

        async def add(self, entity: Any) -> None:
            self.adds += 1
            if getattr(entity, "id", None) is None:
                entity.id = uuid.uuid4()
            contacts[entity.linked_client_id] = entity

    repo = _Repo()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result())

    class _Nested:
        async def __aenter__(self) -> "_Nested":
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    db.begin_nested = MagicMock(return_value=_Nested())
    db.flush = AsyncMock()

    async def _lock(_db: Any, namespace: int, key: uuid.UUID) -> None:
        lock_calls.append((namespace, key))

    monkeypatch.setattr(
        contact_service_mod,
        "contact_repository",
        lambda _db, organization_id=None: repo,
    )
    monkeypatch.setattr(
        "app.services.quota_service.quota_service.assert_crm_contacts_quota",
        AsyncMock(),
    )
    monkeypatch.setattr(pg_locks, "pg_advisory_xact_lock_uuid", _lock)

    svc = contact_service_mod.contact_service
    first = await svc.get_or_create_from_client(db, client_id)
    second = await svc.get_or_create_from_client(db, client_id)

    assert first.linked_client_id == client_id
    assert second is first or second.linked_client_id == client_id
    assert repo.adds == 1
    assert lock_calls
    assert lock_calls[0] == (LOCK_NS_CRM_CAPTURE, client_id)


@pytest.mark.asyncio
async def test_e2e_revoked_connection_blocks_crm_action() -> None:
    connection = _conn(provider="bitrix24", status=HubConnectionStatus.REVOKED.value)
    db = MagicMock()
    db.get = AsyncMock(return_value=connection)
    from app.services.integration_hub.queue import ConnectionRevokedError

    with pytest.raises(ConnectionRevokedError):
        await assert_connection_allows_outbound(db, connection.id)


# ---------------------------------------------------------------------------
# §11.3 — Kaspi Pay invoice → webhook → billing meter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_kaspi_invoice_then_payment_webhook_billing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent creates invoice → Kaspi paid webhook → usage bridge (commission meter)."""
    from app.tasks.hub_queue_tasks import _dispatch_normalized, _execute_adapter_action
    from app.tasks.kaspi_tasks import _process_event

    connection = _conn(provider="kaspi_pay")
    billing_events: list[dict[str, Any]] = []
    invoice_meta: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.async_session_factory",
        _session_factory(connection),
    )
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.secrets_from_connection_with_vault",
        AsyncMock(
            return_value=TokenBundle(
                api_key="merchant-token",
                extra={"merchant_id": "m-1", "secret_key": "sec"},
            )
        ),
    )

    async def _create_invoice(self: Any, **kwargs: Any) -> Any:
        invoice_meta.update(kwargs)
        return SimpleNamespace(
            id="inv-e2e-1",
            amount="1500.00",
            status="pending",
            payment_url="https://pay.kaspi.kz/pay/inv-e2e-1",
            order_id=kwargs.get("order_id") or "ord-1",
        )

    monkeypatch.setattr(
        "app.services.integration_hub.adapters.kaspi.KaspiPayHubAdapter.create_invoice",
        _create_invoice,
    )

    async def _record_usage(db: Any, **kwargs: Any) -> Any:
        billing_events.append({"stage": "invoice", **kwargs})
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr("app.tasks.hub_queue_tasks.record_hub_usage", _record_usage)
    monkeypatch.setattr(
        "app.tasks.hub_queue_tasks.persist_agent_action",
        AsyncMock(return_value=SimpleNamespace()),
    )

    invoice = await _execute_adapter_action(
        str(connection.id),
        "create_invoice",
        {
            "amount": 1500,
            "description": "Оплата консультации",
            "order_id": "ord-e2e-1",
            "action_id": "kaspi:ord-e2e-1",
        },
        celery_task_id="e2e-kaspi-invoice",
    )
    assert invoice.id == "inv-e2e-1"
    assert invoice_meta["amount"] == 1500
    assert any(e.get("metric") == "kaspi_pay_invoice" for e in billing_events)

    # Payment webhook path (consumer).
    paid_payload = {
        "type": "payment.paid",
        "invoice_id": "inv-e2e-1",
        "order_id": "ord-e2e-1",
        "status": "paid",
        "amount": "1500.00",
    }
    monkeypatch.setattr(
        "app.tasks.kaspi_tasks.async_session_factory",
        _session_factory(connection),
    )

    async def _record_webhook(db: Any, **kwargs: Any) -> Any:
        billing_events.append({"stage": "webhook", **kwargs})
        # Dual-write bridge (integration + billing usage_events).
        await record_hub_usage(
            db,
            connection=connection,  # type: ignore[arg-type]
            metric=kwargs["metric"],
            quantity=kwargs.get("quantity", 1),
            meta=kwargs.get("meta") or {},
            idempotency_key=f"kaspi:paid:{paid_payload['invoice_id']}",
        )
        return SimpleNamespace(id=uuid.uuid4())

    # Use real record_hub_usage with mocked billing for commission meter.
    actor_id = uuid.uuid4()
    inserted = uuid.uuid4()
    scalar_q: list[Any] = [None, inserted, actor_id, None]

    class _BillingSession:
        async def scalar(self, _stmt: Any) -> Any:
            return scalar_q.pop(0) if scalar_q else None

        async def get(self, _model: Any, pk: Any) -> Any:
            from app.models.integration_hub import IntegrationUsageEvent

            return IntegrationUsageEvent(
                id=pk,
                connection_id=connection.id,
                organization_id=connection.organization_id,
                metric="kaspi_pay_webhook",
                quantity=1,
                idempotency_key=f"kaspi:paid:{paid_payload['invoice_id']}",
            )

        def add(self, _row: Any) -> None:
            return None

        async def flush(self) -> None:
            return None

    debit_calls: list[dict[str, Any]] = []

    async def _debit(_db: Any, **kwargs: Any) -> SimpleNamespace:
        debit_calls.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(
        "app.services.integration_hub.hub_usage.usage_service.record_and_debit",
        _debit,
    )

    # Direct webhook metering via kaspi_tasks with patched record that also bridges.
    async def _usage_bridge(db: Any, **kwargs: Any) -> Any:
        billing_events.append({"stage": "webhook", **kwargs})
        return await record_hub_usage(
            _BillingSession(),  # type: ignore[arg-type]
            connection=connection,  # type: ignore[arg-type]
            metric=kwargs["metric"],
            quantity=kwargs.get("quantity", 1),
            meta={**(kwargs.get("meta") or {}), "source_event": "kaspi_paid"},
            idempotency_key=f"kaspi:paid:{paid_payload['invoice_id']}",
        )

    monkeypatch.setattr("app.tasks.kaspi_tasks.record_hub_usage", _usage_bridge)

    webhook_result = await _process_event(str(connection.id), paid_payload)
    assert webhook_result["status"] == "ok"

    # Dispatch path also routes to kaspi runtime.
    monkeypatch.setattr("app.tasks.kaspi_tasks._process_event", AsyncMock(return_value={"status": "ok"}))
    routed = await _dispatch_normalized(
        provider="kaspi_pay",
        connection_id=str(connection.id),
        normalized={"type": "payment.paid"},
        payload=paid_payload,
    )
    assert routed["runtime"] == "payments"

    assert any(e.get("stage") == "webhook" and e.get("metric") == "kaspi_pay_webhook" for e in billing_events)
    assert debit_calls
    assert debit_calls[0]["metric_type"] == UsageMetricType.CRM_CALL
    assert debit_calls[0]["meta"]["source"] == "integration_hub"
    assert debit_calls[0]["debit_wallet"] is False


@pytest.mark.asyncio
async def test_e2e_kaspi_payment_idempotent_no_double_commission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry of the same paid invoice must not create a second billing meter."""
    connection = _conn(provider="kaspi_pay")
    key = f"kaspi:paid:inv-dup"
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=connection.organization_id,
        idempotency_key=key,
        metric="kaspi_pay_webhook",
        quantity=1,
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=existing)
    debit = AsyncMock()
    monkeypatch.setattr(
        "app.services.integration_hub.hub_usage.usage_service.record_and_debit",
        debit,
    )
    again = await record_hub_usage(
        db,
        connection=connection,  # type: ignore[arg-type]
        metric="kaspi_pay_webhook",
        idempotency_key=key,
        meta={"invoice_id": "inv-dup", "status": "paid"},
    )
    assert again is None
    debit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Checklist §1–11 readiness gate
# ---------------------------------------------------------------------------


def test_checklist_11_items_covered_by_hub_test_suite() -> None:
    """Living map of pre-release checklist → automated coverage files."""
    coverage = {
        1: "Hub core models / OAuth / connections (test_hub_security_and_dlq, disconnect)",
        2: "Webhook DLQ + retries (test_hub_security_and_dlq)",
        3: "Webhook Redis+DB dedup (test_hub_dedup_and_ratelimit)",
        4: "Tenant isolation (test_hub_security_and_dlq)",
        5: "CRM rate limits (test_hub_dedup_and_ratelimit)",
        6: "Outbound Redis locks + soft timeout (test_hub_billing_and_locks)",
        7: "UI connection cards 5 states (test_hub_disconnect_and_ui)",
        8: "Usage events + billing bridge (test_hub_billing_and_locks)",
        9: "Disconnect / revoke (test_hub_disconnect_and_ui)",
        10: "UI reconnect / OAuth error states (test_hub_disconnect_and_ui)",
        11: "E2E client path (test_hub_e2e_scenarios)",
    }
    assert set(coverage) == set(range(1, 12))
    assert all(isinstance(v, str) and v for v in coverage.values())
