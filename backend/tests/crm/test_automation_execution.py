"""Native CRM Phase B step 2 — automation evaluator & executor."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.core.url_safety import assert_safe_public_https_url
from app.models.crm.automation_rule import AutomationTriggerType, CrmAutomationRule
from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.note import CrmNote
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.crm.tag import CrmTag
from app.models.crm.timeline_event import CrmTimelineEvent
from app.schemas.crm.deals import CrmDealCreate
from app.services.crm.automation_evaluator_service import automation_evaluator_service
from app.services.crm.automation_executor_service import AutomationExecutorService
from app.services.crm.deal_service import DealService
from app.services.crm.note_service import NoteService
from app.services.crm.tag_service import TagService
from app.services.crm.timeline_service import TimelineService
from app.services.flow_parser import FlowExecutor


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self) -> None:
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}
        self.rules: dict[uuid.UUID, CrmAutomationRule] = {}
        self.tags: dict[uuid.UUID, CrmTag] = {}
        self.deal_tags: set[tuple[uuid.UUID, uuid.UUID]] = set()
        self.notes: dict[uuid.UUID, CrmNote] = {}
        self.events: dict[uuid.UUID, CrmTimelineEvent] = {}


class FlushSession:
    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeAutomationRuleRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get_active_rules_by_trigger(
        self,
        trigger_type: AutomationTriggerType,
    ) -> list[CrmAutomationRule]:
        rows = [
            r
            for r in self.store.rules.values()
            if r.organization_id == self.organization_id
            and r.is_active is True
            and r.trigger_type == trigger_type
        ]
        return sorted(rows, key=lambda r: r.created_at)


class FakeDealRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    def _attach(self, deal: CrmDeal) -> CrmDeal:
        deal.stage = self.store.stages.get(deal.stage_id)
        deal.pipeline = self.store.pipelines.get(deal.pipeline_id)
        deal.contact = self.store.contacts.get(deal.contact_id) if deal.contact_id else None
        tag_ids = [t for d, t in self.store.deal_tags if d == deal.id]
        deal.tags = [self.store.tags[t] for t in tag_ids if t in self.store.tags]
        return deal

    async def add(self, entity: CrmDeal) -> CrmDeal:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.deals[entity.id] = entity
        return entity

    async def get(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = self.store.deals.get(deal_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_with_relations(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = await self.get(deal_id)
        return self._attach(row) if row else None

    async def get_with_relations_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get_with_relations(deal_id)

    async def get_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get(deal_id)


class FakePipelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row


class FakeStageRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get_in_pipeline(
        self, pipeline_id: uuid.UUID, stage_id: uuid.UUID
    ) -> CrmStage | None:
        row = self.store.stages.get(stage_id)
        if (
            row is None
            or row.organization_id != self.organization_id
            or row.pipeline_id != pipeline_id
        ):
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


class FakeAccountRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, _account_id: uuid.UUID) -> Any:
        return None


class FakeTagRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, entity_id: uuid.UUID) -> CrmTag | None:
        row = self.store.tags.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def attach_to_deal(self, *, deal_id: uuid.UUID, tag_id: uuid.UUID) -> bool:
        key = (deal_id, tag_id)
        if key in self.store.deal_tags:
            return False
        self.store.deal_tags.add(key)
        return True


class FakeNoteRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmNote) -> CrmNote:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        self.store.notes[entity.id] = entity
        return entity


class FakeTimelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmTimelineEvent) -> CrmTimelineEvent:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        self.store.events[entity.id] = entity
        return entity

    async def list_for_deal(self, *args: Any, **kwargs: Any) -> list[CrmTimelineEvent]:
        return []


def _seed_funnel(store: Store, org: uuid.UUID) -> tuple[CrmPipeline, CrmStage, CrmStage, CrmContact]:
    pipeline = CrmPipeline(
        id=uuid.uuid4(),
        organization_id=org,
        name="Sales",
        position=0,
        is_default=True,
        created_at=_now(),
        updated_at=_now(),
    )
    stage_a = CrmStage(
        id=uuid.uuid4(),
        organization_id=org,
        pipeline_id=pipeline.id,
        name="New",
        position=0,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    stage_b = CrmStage(
        id=uuid.uuid4(),
        organization_id=org,
        pipeline_id=pipeline.id,
        name="Qualified",
        position=1,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    contact = CrmContact(
        id=uuid.uuid4(),
        organization_id=org,
        first_name="Ada",
        last_name="Lovelace",
        source="bot",
        created_at=_now(),
        updated_at=_now(),
        custom_fields={},
    )
    store.pipelines[pipeline.id] = pipeline
    store.stages[stage_a.id] = stage_a
    store.stages[stage_b.id] = stage_b
    store.contacts[contact.id] = contact
    return pipeline, stage_a, stage_b, contact


def _add_rule(
    store: Store,
    org: uuid.UUID,
    *,
    trigger_type: AutomationTriggerType,
    actions: list[dict[str, Any]],
    trigger_config: dict[str, Any] | None = None,
    conditions: dict[str, Any] | None = None,
    name: str = "Rule",
) -> CrmAutomationRule:
    rule = CrmAutomationRule(
        id=uuid.uuid4(),
        organization_id=org,
        name=name,
        is_active=True,
        trigger_type=trigger_type,
        trigger_config=trigger_config or {},
        conditions=conditions or {},
        actions=actions,
        created_at=_now(),
        updated_at=_now(),
    )
    store.rules[rule.id] = rule
    return rule


def _bind(store: Store) -> tuple[DealService, AutomationExecutorService, TagService]:
    deal_mod = sys.modules["app.services.crm.deal_service"]
    tag_mod = sys.modules["app.services.crm.tag_service"]
    note_mod = sys.modules["app.services.crm.note_service"]
    exec_mod = sys.modules["app.services.crm.automation_executor_service"]
    timeline_mod = sys.modules["app.services.crm.timeline_service"]

    tls = TimelineService()
    tls._repo = lambda _db, org: FakeTimelineRepo(store, org)  # type: ignore[method-assign]
    timeline_mod.timeline_service = tls
    deal_mod.timeline_service = tls  # type: ignore[attr-defined]
    tag_mod.timeline_service = tls
    note_mod.timeline_service = tls

    deals = DealService()
    deals._deals = lambda _db, org, **_kw: FakeDealRepo(store, org)  # type: ignore[method-assign]
    deals._pipelines = lambda _db, org: FakePipelineRepo(store, org)  # type: ignore[method-assign]
    deals._stages = lambda _db, org: FakeStageRepo(store, org)  # type: ignore[method-assign]
    deals._contacts = lambda _db, org: FakeContactRepo(store, org)  # type: ignore[method-assign]
    deals._accounts = lambda _db, org: FakeAccountRepo(store, org)  # type: ignore[method-assign]

    tags = TagService()
    tags._repo = lambda _db, org: FakeTagRepo(store, org)  # type: ignore[method-assign]
    tag_mod.deal_repository = lambda db, *, organization_id: FakeDealRepo(store, organization_id)  # type: ignore[assignment]
    tag_mod.tag_service = tags

    notes = NoteService()
    notes._repo = lambda _db, org: FakeNoteRepo(store, org)  # type: ignore[method-assign]
    note_mod.deal_repository = lambda db, *, organization_id: FakeDealRepo(store, organization_id)  # type: ignore[assignment]
    note_mod.contact_repository = lambda db, *, organization_id: FakeContactRepo(store, organization_id)  # type: ignore[assignment]
    note_mod.note_service = notes

    executor = AutomationExecutorService()
    executor._rules_repo = lambda _db, org: FakeAutomationRuleRepo(store, org)  # type: ignore[method-assign]
    exec_mod.automation_rule_repository = (  # type: ignore[assignment]
        lambda db, *, organization_id: FakeAutomationRuleRepo(store, organization_id)
    )
    exec_mod.deal_repository = (  # type: ignore[assignment]
        lambda db, *, organization_id: FakeDealRepo(store, organization_id)
    )
    exec_mod.contact_repository = (  # type: ignore[assignment]
        lambda db, *, organization_id: FakeContactRepo(store, organization_id)
    )
    exec_mod.automation_executor_service = executor

    deal_svc_mod = sys.modules["app.services.crm.deal_service"]
    deal_svc_mod.deal_service = deals

    async def _dispatch(
        db: Any,
        organization_id: uuid.UUID,
        trigger_type: AutomationTriggerType,
        deal: CrmDeal,
        *,
        context_extra: dict | None = None,
    ) -> None:
        await executor.run_triggers(db, trigger_type, deal, context_extra=context_extra)

    deals._dispatch_automations = _dispatch  # type: ignore[method-assign]

    return deals, executor, tags


def test_evaluator_reuses_flow_parser_condition_matches() -> None:
    assert hasattr(FlowExecutor, "_condition_matches")
    deal = CrmDeal(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        pipeline_id=uuid.uuid4(),
        stage_id=uuid.uuid4(),
        title="T",
        amount=Decimal("1500.00"),
        currency="KZT",
        status=DealStatus.OPEN,
        custom_fields={},
    )
    ctx = automation_evaluator_service.build_context(deal, tags=["vip"])
    assert ctx["deal.amount"] == Decimal("1500.00")
    assert ctx["deal.status"] == "open"
    assert automation_evaluator_service.evaluate({}, ctx) is True
    assert (
        automation_evaluator_service.evaluate(
            {"condition_type": "expression", "expression": "true"},
            ctx,
        )
        is True
    )
    assert (
        automation_evaluator_service.evaluate(
            {"condition_type": "customer_tag", "tag": "vip"},
            ctx,
        )
        is True
    )
    assert (
        automation_evaluator_service.evaluate(
            {"condition_type": "customer_tag", "tag": "cold"},
            ctx,
        )
        is False
    )
    assert (
        automation_evaluator_service.evaluate(
            {
                "op": "and",
                "rules": [
                    {"condition_type": "expression", "expression": "true"},
                    {"condition_type": "customer_tag", "tag": "vip"},
                ],
            },
            ctx,
        )
        is True
    )


@pytest.mark.asyncio
async def test_deal_created_adds_tag_via_automation() -> None:
    store = Store()
    deals, _, _ = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed_funnel(store, org)

    tag = CrmTag(
        id=uuid.uuid4(),
        organization_id=org,
        name="Hot",
        color="#ff0000",
        created_at=_now(),
        updated_at=_now(),
    )
    store.tags[tag.id] = tag
    _add_rule(
        store,
        org,
        trigger_type=AutomationTriggerType.DEAL_CREATED,
        actions=[{"type": "add_tag", "tag_id": str(tag.id)}],
        name="Tag on create",
    )

    created = await deals.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Auto tagged",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
    )
    assert (created.id, tag.id) in store.deal_tags


@pytest.mark.asyncio
async def test_stage_entered_moves_and_adds_note() -> None:
    store = Store()
    deals, executor, _ = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, stage_a, stage_b, contact = _seed_funnel(store, org)

    created = await deals.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(
            title="Move me",
            pipeline_id=pipeline.id,
            stage_id=stage_a.id,
            contact_id=contact.id,
        ),
        skip_automations=True,
    )

    _add_rule(
        store,
        org,
        trigger_type=AutomationTriggerType.STAGE_ENTERED,
        trigger_config={"stage_id": str(stage_b.id)},
        actions=[{"type": "add_note", "text": "Entered qualified"}],
        name="Note on enter",
    )

    moved = await deals.move_stage(db, org, created.id, stage_b.id)  # type: ignore[arg-type]
    assert moved.stage_id == stage_b.id
    assert any(n.text == "Entered qualified" for n in store.notes.values())

    # Wrong stage in trigger_config must not fire
    store.notes.clear()
    _add_rule(
        store,
        org,
        trigger_type=AutomationTriggerType.STAGE_ENTERED,
        trigger_config={"stage_id": str(uuid.uuid4())},
        actions=[{"type": "add_note", "text": "Should not fire"}],
        name="Wrong stage",
    )
    # Move back then forward again — wrong-stage rule must skip
    await deals.move_stage(db, org, created.id, stage_a.id, skip_automations=True)  # type: ignore[arg-type]
    await deals.move_stage(db, org, created.id, stage_b.id)  # type: ignore[arg-type]
    assert not any(n.text == "Should not fire" for n in store.notes.values())
    # Existing correct rule should have fired again
    assert any(n.text == "Entered qualified" for n in store.notes.values())

    # Direct executor call still works
    deal_row = store.deals[created.id]
    deal_row.stage_id = stage_b.id
    results = await executor.run_triggers(
        db,  # type: ignore[arg-type]
        AutomationTriggerType.STAGE_ENTERED,
        deal_row,
    )
    assert any(r["matched"] for r in results)


@pytest.mark.asyncio
async def test_send_webhook_ssrf_blocks_localhost() -> None:
    store = Store()
    _, executor, _ = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()
    pipeline, stage_a, _, contact = _seed_funnel(store, org)

    deal = CrmDeal(
        id=uuid.uuid4(),
        organization_id=org,
        pipeline_id=pipeline.id,
        stage_id=stage_a.id,
        contact_id=contact.id,
        title="Webhook deal",
        amount=Decimal("0"),
        currency="KZT",
        status=DealStatus.OPEN,
        created_at=_now(),
        updated_at=_now(),
        custom_fields={},
    )
    store.deals[deal.id] = deal

    _add_rule(
        store,
        org,
        trigger_type=AutomationTriggerType.DEAL_CREATED,
        actions=[{"type": "send_webhook", "url": "http://127.0.0.1/admin"}],
        name="SSRF bait",
    )

    results = await executor.run_triggers(
        db,  # type: ignore[arg-type]
        AutomationTriggerType.DEAL_CREATED,
        deal,
    )
    matched = [r for r in results if r["matched"]]
    assert matched
    # Action attempted but blocked — not listed as successfully run
    assert "send_webhook" not in matched[0]["actions_run"]

    with pytest.raises(ValueError):
        assert_safe_public_https_url("http://127.0.0.1/admin")
    with pytest.raises(ValueError):
        assert_safe_public_https_url("https://127.0.0.1/admin")
    with pytest.raises(ValueError):
        assert_safe_public_https_url("http://example.com/ok")


def test_https_only_webhook_guard() -> None:
    with pytest.raises(ValueError, match="https"):
        assert_safe_public_https_url("http://example.com/hook")
