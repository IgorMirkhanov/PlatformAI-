"""Native CRM Phase A step 6 — bridge + auto-capture wiring."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.services.crm.crm_bridge_service import CrmBridgeService
from app.services.crm.deal_service import DealService
from app.services.flow_parser import FlowExecutor


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FlushSession:
    async def flush(self) -> None:
        return None

    async def execute(self, _stmt: Any) -> Any:
        raise AssertionError("Unexpected SQL execute in unit test")

    def begin_nested(self):
        return _NestedSavepoint()


class _NestedSavepoint:
    async def __aenter__(self) -> "_NestedSavepoint":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class Store:
    def __init__(self) -> None:
        self.deals: dict[uuid.UUID, CrmDeal] = {}
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}
        self.client_bot: dict[uuid.UUID, Any] = {}


class FakeDealRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = self.store.deals.get(deal_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_with_relations(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get(deal_id)

    async def get_with_relations_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get_with_relations(deal_id)

    async def get_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get(deal_id)

    async def get_latest_open_for_contact(self, contact_id: uuid.UUID) -> CrmDeal | None:
        rows = [
            d
            for d in self.store.deals.values()
            if d.organization_id == self.organization_id
            and d.contact_id == contact_id
            and d.status == DealStatus.OPEN
        ]
        if not rows:
            return None
        return sorted(rows, key=lambda d: d.updated_at, reverse=True)[0]

    async def add(self, entity: CrmDeal) -> CrmDeal:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.deals[entity.id] = entity
        return entity


class FakeStageRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get_in_pipeline(self, pipeline_id: uuid.UUID, stage_id: uuid.UUID) -> CrmStage | None:
        row = self.store.stages.get(stage_id)
        if (
            row is None
            or row.organization_id != self.organization_id
            or row.pipeline_id != pipeline_id
        ):
            return None
        return row


class FakePipelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row


class FakeContactRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, contact_id: uuid.UUID) -> CrmContact | None:
        row = self.store.contacts.get(contact_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_by_linked_client_id(self, client_id: uuid.UUID) -> CrmContact | None:
        for row in self.store.contacts.values():
            if row.organization_id == self.organization_id and row.linked_client_id == client_id:
                return row
        return None


@pytest.mark.asyncio
async def test_bridge_move_stage_updates_deal(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    store = Store()
    org = uuid.uuid4()
    client_id = uuid.uuid4()
    pipeline_id = uuid.uuid4()
    stage_a = uuid.uuid4()
    stage_b = uuid.uuid4()

    store.pipelines[pipeline_id] = CrmPipeline(
        id=pipeline_id,
        organization_id=org,
        name="Продажи",
        position=0,
        is_default=True,
        created_at=_now(),
        updated_at=_now(),
    )
    store.stages[stage_a] = CrmStage(
        id=stage_a,
        organization_id=org,
        pipeline_id=pipeline_id,
        name="Новый",
        position=0,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    store.stages[stage_b] = CrmStage(
        id=stage_b,
        organization_id=org,
        pipeline_id=pipeline_id,
        name="Переговоры",
        position=1,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    contact = CrmContact(
        id=uuid.uuid4(),
        organization_id=org,
        linked_client_id=client_id,
        first_name="Ada",
        last_name="",
        created_at=_now(),
        updated_at=_now(),
        custom_fields={},
    )
    store.contacts[contact.id] = contact
    deal = CrmDeal(
        id=uuid.uuid4(),
        organization_id=org,
        pipeline_id=pipeline_id,
        stage_id=stage_a,
        contact_id=contact.id,
        title="Open deal",
        amount=Decimal("0"),
        currency="KZT",
        status=DealStatus.OPEN,
        created_at=_now(),
        updated_at=_now(),
        custom_fields={},
    )
    store.deals[deal.id] = deal

    bot = SimpleNamespace(organization_id=org)
    store.client_bot[client_id] = SimpleNamespace(id=client_id, bot=bot)

    deals = DealService()
    deals._deals = lambda _db, o, **_kw: FakeDealRepo(store, o)  # type: ignore[method-assign]
    deals._pipelines = lambda _db, o: FakePipelineRepo(store, o)  # type: ignore[method-assign]
    deals._stages = lambda _db, o: FakeStageRepo(store, o)  # type: ignore[method-assign]
    deals._contacts = lambda _db, o: FakeContactRepo(store, o)  # type: ignore[method-assign]
    deals._accounts = lambda _db, o: SimpleNamespace(get=lambda *_a, **_k: None)  # type: ignore[method-assign]

    async def _noop_log(*_a: Any, **_k: Any) -> None:
        return None

    deals._log_event = _noop_log  # type: ignore[method-assign]

    bridge = CrmBridgeService()

    class _Result:
        def __init__(self, client: Any) -> None:
            self._client = client

        def scalar_one_or_none(self) -> Any:
            return self._client

    async def fake_execute(stmt: Any) -> Any:  # noqa: ARG001
        return _Result(store.client_bot[client_id])

    db = FlushSession()
    db.execute = fake_execute  # type: ignore[method-assign]

    bridge_mod = sys.modules["app.services.crm.crm_bridge_service"]
    monkeypatch.setattr(
        bridge_mod,
        "contact_repository",
        lambda _db, *, organization_id: FakeContactRepo(store, organization_id),
    )
    monkeypatch.setattr(
        bridge_mod,
        "deal_repository",
        lambda _db, *, organization_id: FakeDealRepo(store, organization_id),
    )
    monkeypatch.setattr(bridge_mod, "deal_service", deals)

    result = await bridge.execute_internal_action(
        db,  # type: ignore[arg-type]
        client_id,
        "move_stage",
        {"stage_id": str(stage_b)},
    )
    assert result["success"] is True
    assert store.deals[deal.id].stage_id == stage_b


@pytest.mark.asyncio
async def test_flow_executor_internal_crm_action_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    stage_id = uuid.uuid4()
    client_id = uuid.uuid4()
    graph = {
        "nodes": [
            {"id": "t1", "type": "trigger", "data": {}},
            {
                "id": "c1",
                "type": "crm_action",
                "data": {
                    "target": "internal",
                    "action": "move_stage",
                    "params": {"stage_id": str(stage_id)},
                },
            },
            {"id": "m1", "type": "text_message", "data": {"text": "Done"}},
        ],
        "edges": [
            {"id": "e1", "source": "t1", "target": "c1"},
            {"id": "e2", "source": "c1", "target": "m1"},
        ],
    }

    async def fake_bridge(db: Any, cid: uuid.UUID, action: str, params: dict[str, Any]) -> dict[str, Any]:
        assert cid == client_id
        assert action == "move_stage"
        assert params["stage_id"] == str(stage_id)
        return {"success": True, "action": "move_stage"}

    bridge_mod = sys.modules["app.services.crm.crm_bridge_service"]
    monkeypatch.setattr(bridge_mod.crm_bridge_service, "execute_internal_action", fake_bridge)

    executor = FlowExecutor(graph)
    result = await executor.execute(
        current_step_id=None,
        incoming_message="hi",
        context={},
        db=FlushSession(),  # type: ignore[arg-type]
        bot_id=uuid.uuid4(),
        client_id=client_id,
    )
    assert result.error is None
    assert result.variables.get("crm_result", {}).get("success") is True
    # Continues past CRM node to text message
    assert result.node_id == "m1"
    assert result.text == "Done"


def test_migration_034_and_capture_task_routed() -> None:
    import pathlib

    from app.core.celery_app import celery_app
    from app.tasks.crm_tasks import capture_lead_task

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "034_crm_settings.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "crm_settings" in text
    assert "033_crm_tags_custom_fields" in text
    assert "auto_capture_enabled" in text

    assert capture_lead_task.name == "app.tasks.crm_tasks.capture_lead_task"
    routes = celery_app.conf.task_routes or {}
    assert routes["app.tasks.crm_tasks.capture_lead_task"]["queue"]


def test_webhook_skips_external_queue_for_internal_target() -> None:
    from app.services import webhook_service

    # Should return immediately without raising when target=internal
    webhook_service._enqueue_crm_action(
        uuid.uuid4(),
        uuid.uuid4(),
        {"target": "internal", "action": "add_note", "params": {"text": "x"}},
    )
