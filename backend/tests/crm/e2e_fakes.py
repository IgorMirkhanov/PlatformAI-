"""In-memory store + fake CRM repositories for E2E business-flow tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.models.core_models import UserRole
from app.models.crm.api_key import CrmApiKey
from app.models.crm.automation_rule import AutomationTriggerType, CrmAutomationRule
from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.note import CrmNote
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.crm.tag import CrmTag
from app.models.crm.timeline_event import CrmTimelineEvent
from app.models.crm.webhook_subscription import CrmWebhookSubscription
from app.services.crm.deal_access import CrmActor


def now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self) -> None:
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}
        self.tags: dict[uuid.UUID, CrmTag] = {}
        self.deal_tags: set[tuple[uuid.UUID, uuid.UUID]] = set()
        self.notes: dict[uuid.UUID, CrmNote] = {}
        self.events: dict[uuid.UUID, CrmTimelineEvent] = {}
        self.rules: dict[uuid.UUID, CrmAutomationRule] = {}
        self.keys: dict[uuid.UUID, CrmApiKey] = {}
        self.keys_by_hash: dict[str, CrmApiKey] = {}
        self.webhooks: dict[uuid.UUID, CrmWebhookSubscription] = {}


class NestedSavepoint:
    """Stand-in for ``AsyncSession.begin_nested()`` used by CRM/wallet services."""

    async def __aenter__(self) -> "NestedSavepoint":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class FlushSession:
    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def scalar(self, _stmt: Any) -> Any:
        return None

    def begin_nested(self) -> NestedSavepoint:
        return NestedSavepoint()


class FakePipelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmPipeline) -> CrmPipeline:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        entity.stages = list(getattr(entity, "stages", None) or [])
        self.store.pipelines[entity.id] = entity
        return entity

    async def get(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_with_stages(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = await self.get(pipeline_id)
        if row is None:
            return None
        row.stages = sorted(
            [
                s
                for s in self.store.stages.values()
                if s.pipeline_id == pipeline_id and s.organization_id == self.organization_id
            ],
            key=lambda s: s.position,
        )
        return row

    async def get_default(self) -> CrmPipeline | None:
        for p in self.store.pipelines.values():
            if p.organization_id == self.organization_id and p.is_default:
                return await self.get_with_stages(p.id)
        return None

    async def list_with_stages(self, *, limit: int = 50) -> list[CrmPipeline]:
        rows = [
            p for p in self.store.pipelines.values() if p.organization_id == self.organization_id
        ]
        out = []
        for p in rows[:limit]:
            loaded = await self.get_with_stages(p.id)
            if loaded:
                out.append(loaded)
        return out

    async def next_position(self) -> int:
        positions = [
            p.position
            for p in self.store.pipelines.values()
            if p.organization_id == self.organization_id
        ]
        return (max(positions) + 1) if positions else 0


class FakeStageRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmStage) -> CrmStage:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        self.store.stages[entity.id] = entity
        return entity

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

    async def next_position(self, pipeline_id: uuid.UUID) -> int:
        positions = [
            s.position
            for s in self.store.stages.values()
            if s.organization_id == self.organization_id and s.pipeline_id == pipeline_id
        ]
        return (max(positions) + 1) if positions else 0


class FakeContactRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmContact) -> CrmContact:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.contacts[entity.id] = entity
        return entity

    async def get(self, contact_id: uuid.UUID) -> CrmContact | None:
        row = self.store.contacts.get(contact_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def find_by_phone_or_email(
        self, *, phone: str | None = None, email: str | None = None
    ) -> CrmContact | None:
        phone_n = (phone or "").strip() or None
        email_n = (email or "").strip() or None
        for c in self.store.contacts.values():
            if c.organization_id != self.organization_id:
                continue
            if phone_n and c.phone == phone_n:
                return c
            if email_n and (c.email or "").lower() == email_n.lower():
                return c
        return None

    async def count_filtered(self, **_kw: Any) -> int:
        return len(
            [c for c in self.store.contacts.values() if c.organization_id == self.organization_id]
        )


class FakeAccountRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, _account_id: uuid.UUID) -> Any:
        return None


class FakeDealRepo:
    def __init__(
        self,
        store: Store,
        organization_id: uuid.UUID,
        *,
        viewer_user_id: uuid.UUID | None = None,
        viewer_role: UserRole | None = None,
        **_kw: Any,
    ) -> None:
        self.store = store
        self.organization_id = organization_id
        self.viewer_user_id = viewer_user_id
        self.viewer_role = viewer_role

    def _actor(self) -> CrmActor | None:
        if self.viewer_user_id is None:
            return None
        return CrmActor(user_id=self.viewer_user_id, role=self.viewer_role or UserRole.OPERATOR)

    def _visible(self, deal: CrmDeal) -> bool:
        if deal.organization_id != self.organization_id:
            return False
        actor = self._actor()
        if actor is None or actor.sees_all_deals:
            return True
        return actor.can_view_deal(deal)

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
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.deals[entity.id] = entity
        return entity

    async def get(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = self.store.deals.get(deal_id)
        if row is None or not self._visible(row):
            return None
        return self._attach(row)

    async def get_with_relations(self, deal_id: uuid.UUID) -> CrmDeal | None:
        return await self.get(deal_id)

    async def get_with_relations_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = self.store.deals.get(deal_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return self._attach(row)

    async def get_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        row = self.store.deals.get(deal_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_deals(self, **filters: Any) -> list[CrmDeal]:
        rows = [d for d in self.store.deals.values() if self._visible(d)]
        if filters.get("pipeline_id"):
            rows = [d for d in rows if d.pipeline_id == filters["pipeline_id"]]
        if filters.get("stage_id"):
            rows = [d for d in rows if d.stage_id == filters["stage_id"]]
        if filters.get("status"):
            rows = [d for d in rows if d.status == filters["status"]]
        limit = int(filters.get("limit") or 50)
        offset = int(filters.get("offset") or 0)
        return [self._attach(d) for d in rows[offset : offset + limit]]

    async def count_deals(self, **filters: Any) -> int:
        rows = await self.get_deals(**{**filters, "limit": 10_000, "offset": 0})
        return len(rows)

    async def count_for_pipeline(self, pipeline_id: uuid.UUID) -> int:
        return len(
            [
                d
                for d in self.store.deals.values()
                if d.organization_id == self.organization_id and d.pipeline_id == pipeline_id
            ]
        )


class FakeTagRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmTag) -> CrmTag:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        self.store.tags[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmTag | None:
        row = self.store.tags.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def list_ordered(self, *, limit: int = 200, offset: int = 0) -> list[CrmTag]:
        rows = [t for t in self.store.tags.values() if t.organization_id == self.organization_id]
        return rows[offset : offset + limit]

    async def count_all(self) -> int:
        return len([t for t in self.store.tags.values() if t.organization_id == self.organization_id])

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
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        self.store.notes[entity.id] = entity
        return entity


class FakeTimelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmTimelineEvent) -> CrmTimelineEvent:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.payload = dict(getattr(entity, "payload", None) or {})
        self.store.events[entity.id] = entity
        return entity

    async def list_events(
        self,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        event_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CrmTimelineEvent]:
        rows = [e for e in self.store.events.values() if e.organization_id == self.organization_id]
        if deal_id is not None:
            rows = [e for e in rows if e.deal_id == deal_id]
        if contact_id is not None:
            rows = [e for e in rows if e.contact_id == contact_id]
        if event_type is not None:
            rows = [e for e in rows if e.event_type == event_type]
        rows = sorted(rows, key=lambda e: e.created_at, reverse=True)
        return rows[offset : offset + limit]

    async def count_events(
        self,
        *,
        deal_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        event_type: str | None = None,
    ) -> int:
        return len(
            await self.list_events(
                deal_id=deal_id,
                contact_id=contact_id,
                event_type=event_type,
                limit=10_000,
            )
        )


class FakeAutomationRuleRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmAutomationRule) -> CrmAutomationRule:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        entity.trigger_config = dict(getattr(entity, "trigger_config", None) or {})
        entity.conditions = dict(getattr(entity, "conditions", None) or {})
        entity.actions = list(getattr(entity, "actions", None) or [])
        self.store.rules[entity.id] = entity
        return entity

    async def list_filtered(self, **_kw: Any) -> list[CrmAutomationRule]:
        return [r for r in self.store.rules.values() if r.organization_id == self.organization_id]

    async def count_filtered(self, **_kw: Any) -> int:
        return len(await self.list_filtered())

    async def get_active_rules_by_trigger(
        self, trigger_type: AutomationTriggerType
    ) -> list[CrmAutomationRule]:
        return [
            r
            for r in self.store.rules.values()
            if r.organization_id == self.organization_id
            and r.is_active
            and r.trigger_type == trigger_type
        ]


class FakeApiKeyRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmApiKey) -> CrmApiKey:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        self.store.keys[entity.id] = entity
        self.store.keys_by_hash[entity.key_hash] = entity
        return entity

    async def list_ordered(self, *, limit: int = 100, offset: int = 0) -> list[CrmApiKey]:
        rows = [k for k in self.store.keys.values() if k.organization_id == self.organization_id]
        return sorted(rows, key=lambda k: k.created_at, reverse=True)[offset : offset + limit]

    async def count_all(self) -> int:
        return len([k for k in self.store.keys.values() if k.organization_id == self.organization_id])

    async def touch_last_used(self, entity: CrmApiKey) -> None:
        entity.last_used_at = now()


class FakeWebhookRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmWebhookSubscription) -> CrmWebhookSubscription:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or now()
        entity.updated_at = getattr(entity, "updated_at", None) or now()
        entity.event_types = list(getattr(entity, "event_types", None) or [])
        self.store.webhooks[entity.id] = entity
        return entity

    async def list_ordered(self, *, limit: int = 100, offset: int = 0) -> list[CrmWebhookSubscription]:
        rows = [
            w for w in self.store.webhooks.values() if w.organization_id == self.organization_id
        ]
        return rows[offset : offset + limit]

    async def count_all(self) -> int:
        return len(
            [w for w in self.store.webhooks.values() if w.organization_id == self.organization_id]
        )


class FakeAnalyticsRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def pipeline_belongs(self, pipeline_id: uuid.UUID) -> bool:
        p = self.store.pipelines.get(pipeline_id)
        return p is not None and p.organization_id == self.organization_id

    async def funnel_stage_rows(
        self, pipeline_id: uuid.UUID, *, start_date: Any = None, end_date: Any = None
    ) -> list[Any]:
        stages = sorted(
            [
                s
                for s in self.store.stages.values()
                if s.organization_id == self.organization_id and s.pipeline_id == pipeline_id
            ],
            key=lambda s: s.position,
        )
        rows = []
        for stage in stages:
            deals = [
                d
                for d in self.store.deals.values()
                if d.organization_id == self.organization_id
                and d.pipeline_id == pipeline_id
                and d.stage_id == stage.id
            ]
            rows.append(
                SimpleNamespace(
                    stage_id=stage.id,
                    stage_name=stage.name,
                    position=stage.position,
                    deal_count=len(deals),
                    amount_sum=sum((d.amount for d in deals), Decimal("0")),
                )
            )
        return rows

    async def funnel_totals(
        self, pipeline_id: uuid.UUID, *, start_date: Any = None, end_date: Any = None
    ) -> Any:
        deals = [
            d
            for d in self.store.deals.values()
            if d.organization_id == self.organization_id and d.pipeline_id == pipeline_id
        ]
        won = sum(1 for d in deals if d.status == DealStatus.WON)
        return SimpleNamespace(total_deals=len(deals), won_deals=won)

    async def manager_performance_rows(self, **_kw: Any) -> list[Any]:
        return []

    async def revenue_forecast_row(self) -> Any:
        opens = [
            d
            for d in self.store.deals.values()
            if d.organization_id == self.organization_id and d.status == DealStatus.OPEN
        ]
        return SimpleNamespace(
            open_deal_count=len(opens),
            forecast_amount=sum((d.amount for d in opens), Decimal("0")),
        )
