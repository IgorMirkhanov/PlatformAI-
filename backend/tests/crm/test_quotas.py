"""Native CRM Phase C step 2 — entity quotas (contacts / open deals / rules)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.crm.automations import router as automations_router
from app.api.endpoints.crm.contacts import router as contacts_router
from app.api.endpoints.crm.deals import router as deals_router
from app.api.endpoints.crm.public_webhooks import router as public_leads_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import SubscriptionPlanName, UserRole
from app.models.crm.automation_rule import AutomationTriggerType, CrmAutomationRule
from app.models.crm.contact import CrmContact
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.users import User
from app.schemas.crm.accounts_contacts import CrmContactCreate
from app.schemas.crm.automations import CrmAutomationRuleCreate
from app.schemas.crm.deals import CrmDealCreate
from app.services.crm.automation_rule_service import (
    AutomationRuleServiceError,
    automation_rule_service,
)
from app.services.crm.contact_service import ContactServiceError, contact_service
from app.services.crm.deal_service import DealServiceError, deal_service
from app.services.quota_service import (
    PLAN_CRM_AUTOMATION_RULES_MAX,
    PLAN_CRM_CONTACTS_MAX,
    PLAN_CRM_DEALS_OPEN_MAX,
    QuotaExceeded,
    QuotaService,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(*, org_id: uuid.UUID) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@crm.test",
        hashed_password="!",
        company_name="Org",
        full_name="Quota Tester",
        company_id=org_id,
        role=UserRole.OWNER,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


class Store:
    def __init__(self) -> None:
        self.contacts: dict[uuid.UUID, CrmContact] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}
        self.rules: dict[uuid.UUID, CrmAutomationRule] = {}
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}


class FlushSession:
    async def flush(self) -> None:
        return None


class FakeContactRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmContact) -> CrmContact:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.contacts[entity.id] = entity
        return entity

    async def get(self, entity_id: uuid.UUID) -> CrmContact | None:
        row = self.store.contacts.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def count_filtered(self, **_kwargs: Any) -> int:
        return len(
            [c for c in self.store.contacts.values() if c.organization_id == self.organization_id]
        )

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

    async def get_by_linked_client_id(self, _client_id: uuid.UUID) -> CrmContact | None:
        return None


class FakeAccountRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, _account_id: uuid.UUID) -> Any:
        return None


class FakePipelineRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def get(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def get_with_stages(self, pipeline_id: uuid.UUID) -> CrmPipeline | None:
        return await self.get(pipeline_id)

    async def get_default(self) -> CrmPipeline | None:
        for p in self.store.pipelines.values():
            if p.organization_id == self.organization_id and p.is_default:
                return p
        return None

    async def list_with_stages(self, *, limit: int = 50) -> list[CrmPipeline]:
        rows = [
            p for p in self.store.pipelines.values() if p.organization_id == self.organization_id
        ]
        return rows[:limit]


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


class FakeDealRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmDeal) -> CrmDeal:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.custom_fields = dict(getattr(entity, "custom_fields", None) or {})
        self.store.deals[entity.id] = entity
        return entity

    async def get_with_relations_unscoped(self, deal_id: uuid.UUID) -> CrmDeal | None:
        deal = self.store.deals.get(deal_id)
        if deal is None or deal.organization_id != self.organization_id:
            return None
        deal.stage = self.store.stages.get(deal.stage_id)
        return deal

    async def count_deals(self, *, status: DealStatus | None = None, **_kw: Any) -> int:
        rows = [d for d in self.store.deals.values() if d.organization_id == self.organization_id]
        if status is not None:
            rows = [d for d in rows if d.status == status]
        return len(rows)


class FakeAutomationRepo:
    def __init__(self, store: Store, organization_id: uuid.UUID) -> None:
        self.store = store
        self.organization_id = organization_id

    async def add(self, entity: CrmAutomationRule) -> CrmAutomationRule:
        entity.id = getattr(entity, "id", None) or uuid.uuid4()
        entity.organization_id = self.organization_id
        entity.created_at = getattr(entity, "created_at", None) or _now()
        entity.updated_at = getattr(entity, "updated_at", None) or _now()
        entity.trigger_config = dict(getattr(entity, "trigger_config", None) or {})
        entity.conditions = dict(getattr(entity, "conditions", None) or {})
        entity.actions = list(getattr(entity, "actions", None) or [])
        self.store.rules[entity.id] = entity
        return entity

    async def count_filtered(self, **_kwargs: Any) -> int:
        return len(
            [r for r in self.store.rules.values() if r.organization_id == self.organization_id]
        )


def _seed_pipeline(store: Store, org_id: uuid.UUID) -> tuple[CrmPipeline, CrmStage]:
    pipeline = CrmPipeline(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="Sales",
        position=0,
        is_default=True,
        created_at=_now(),
        updated_at=_now(),
    )
    stage = CrmStage(
        id=uuid.uuid4(),
        organization_id=org_id,
        pipeline_id=pipeline.id,
        name="New",
        position=0,
        color=None,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    pipeline.stages = [stage]
    store.pipelines[pipeline.id] = pipeline
    store.stages[stage.id] = stage
    return pipeline, stage


def _bind_repos(monkeypatch: pytest.MonkeyPatch, store: Store) -> None:
    import sys

    def _contacts(db: Any, *, organization_id: uuid.UUID) -> FakeContactRepo:
        return FakeContactRepo(store, organization_id)

    def _accounts(db: Any, *, organization_id: uuid.UUID) -> FakeAccountRepo:
        return FakeAccountRepo(store, organization_id)

    def _pipelines(db: Any, *, organization_id: uuid.UUID) -> FakePipelineRepo:
        return FakePipelineRepo(store, organization_id)

    def _stages(db: Any, *, organization_id: uuid.UUID) -> FakeStageRepo:
        return FakeStageRepo(store, organization_id)

    def _deals(db: Any, *, organization_id: uuid.UUID, **_kw: Any) -> FakeDealRepo:
        return FakeDealRepo(store, organization_id)

    def _rules(db: Any, *, organization_id: uuid.UUID) -> FakeAutomationRepo:
        return FakeAutomationRepo(store, organization_id)

    contact_mod = sys.modules["app.services.crm.contact_service"]
    deal_mod = sys.modules["app.services.crm.deal_service"]
    rules_mod = sys.modules["app.services.crm.automation_rule_service"]
    inbound_mod = sys.modules["app.services.crm.inbound_lead_service"]
    quota_mod = sys.modules["app.services.quota_service"]

    monkeypatch.setattr(contact_mod, "contact_repository", _contacts, raising=False)
    monkeypatch.setattr(contact_mod, "account_repository", _accounts, raising=False)
    monkeypatch.setattr(deal_mod, "deal_repository", _deals, raising=False)
    monkeypatch.setattr(deal_mod, "pipeline_repository", _pipelines, raising=False)
    monkeypatch.setattr(deal_mod, "stage_repository", _stages, raising=False)
    monkeypatch.setattr(deal_mod, "contact_repository", _contacts, raising=False)
    monkeypatch.setattr(deal_mod, "account_repository", _accounts, raising=False)
    monkeypatch.setattr(rules_mod, "automation_rule_repository", _rules, raising=False)
    monkeypatch.setattr(inbound_mod, "contact_repository", _contacts, raising=False)
    monkeypatch.setattr(inbound_mod, "pipeline_repository", _pipelines, raising=False)
    monkeypatch.setattr(quota_mod, "contact_repository", _contacts, raising=False)
    monkeypatch.setattr(quota_mod, "deal_repository", _deals, raising=False)
    monkeypatch.setattr(quota_mod, "automation_rule_repository", _rules, raising=False)

    # Instance helpers (services call self._contacts / self._deals, not the factory directly)
    contact_service._contacts = (  # type: ignore[method-assign]
        lambda db, organization_id: FakeContactRepo(store, organization_id)
    )
    contact_service._accounts = (  # type: ignore[method-assign]
        lambda db, organization_id: FakeAccountRepo(store, organization_id)
    )
    deal_service._deals = (  # type: ignore[method-assign]
        lambda db, organization_id, **_kw: FakeDealRepo(store, organization_id)
    )
    deal_service._deals_unscoped = (  # type: ignore[method-assign]
        lambda db, organization_id: FakeDealRepo(store, organization_id)
    )
    deal_service._pipelines = (  # type: ignore[method-assign]
        lambda db, organization_id: FakePipelineRepo(store, organization_id)
    )
    deal_service._stages = (  # type: ignore[method-assign]
        lambda db, organization_id: FakeStageRepo(store, organization_id)
    )
    deal_service._contacts = (  # type: ignore[method-assign]
        lambda db, organization_id: FakeContactRepo(store, organization_id)
    )
    deal_service._accounts = (  # type: ignore[method-assign]
        lambda db, organization_id: FakeAccountRepo(store, organization_id)
    )
    automation_rule_service._repo = (  # type: ignore[method-assign]
        lambda db, organization_id: FakeAutomationRepo(store, organization_id)
    )


def _limit_free_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(PLAN_CRM_CONTACTS_MAX, SubscriptionPlanName.FREE, 1)
    monkeypatch.setitem(PLAN_CRM_DEALS_OPEN_MAX, SubscriptionPlanName.FREE, 1)
    monkeypatch.setitem(PLAN_CRM_AUTOMATION_RULES_MAX, SubscriptionPlanName.FREE, 1)

    async def _free_plan(
        self: Any, _db: Any, _oid: uuid.UUID
    ) -> SubscriptionPlanName:
        return SubscriptionPlanName.FREE

    monkeypatch.setattr(QuotaService, "_plan", _free_plan)


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_contact_quota_blocks_second(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    db = FlushSession()
    first = await contact_service.create_contact(
        db,  # type: ignore[arg-type]
        org,
        CrmContactCreate(first_name="One"),
    )
    assert first.first_name == "One"

    with pytest.raises(ContactServiceError) as exc:
        await contact_service.create_contact(
            db,  # type: ignore[arg-type]
            org,
            CrmContactCreate(first_name="Two"),
        )
    assert exc.value.status_code == 402
    assert "contact" in exc.value.message.lower()


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_deal_quota_blocks_second_open(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    pipe, stage = _seed_pipeline(store, org)
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(deal_service, "_log_event", _noop)
    monkeypatch.setattr(deal_service, "_dispatch_automations", _noop)

    db = FlushSession()
    first = await deal_service.create_deal(
        db,  # type: ignore[arg-type]
        org,
        CrmDealCreate(title="Deal 1", pipeline_id=pipe.id, stage_id=stage.id),
    )
    assert first.title == "Deal 1"

    with pytest.raises(DealServiceError) as exc:
        await deal_service.create_deal(
            db,  # type: ignore[arg-type]
            org,
            CrmDealCreate(title="Deal 2", pipeline_id=pipe.id, stage_id=stage.id),
        )
    assert exc.value.status_code == 402


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_automation_rule_quota_blocks_second(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    db = FlushSession()
    await automation_rule_service.create_rule(
        db,  # type: ignore[arg-type]
        org,
        CrmAutomationRuleCreate(
            name="Rule 1",
            trigger_type=AutomationTriggerType.DEAL_CREATED,
            actions=[{"type": "add_tag", "tag_name": "x"}],
        ),
    )
    with pytest.raises(AutomationRuleServiceError) as exc:
        await automation_rule_service.create_rule(
            db,  # type: ignore[arg-type]
            org,
            CrmAutomationRuleCreate(
                name="Rule 2",
                trigger_type=AutomationTriggerType.DEAL_CREATED,
                actions=[{"type": "add_tag", "tag_name": "y"}],
            ),
        )
    assert exc.value.status_code == 402


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_get_or_create_from_client_soft_fails_on_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store()
    org = uuid.uuid4()
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    await contact_service.create_contact(
        FlushSession(),  # type: ignore[arg-type]
        org,
        CrmContactCreate(first_name="Filled"),
    )

    from app.models.core_models import Bot, Client, PlatformType
    from app.services.crm.contact_service import ContactService

    class CaptureSession(FlushSession):
        def __init__(self, client: Client) -> None:
            self._client = client

        async def execute(self, _stmt: Any) -> Any:
            class _R:
                def scalar_one_or_none(self_inner) -> Client:
                    return self._client

            return _R()

    bot = Bot(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        organization_id=org,
        name="Bot",
        platform_type=PlatformType.WHATSAPP,
        is_active=True,
        credentials={},
    )
    client = Client(
        id=uuid.uuid4(),
        bot_id=bot.id,
        external_id="1",
        username="u",
        first_name="New",
        current_step_id="",
        is_paused_by_operator=False,
    )
    client.bot = bot

    with pytest.raises(ContactServiceError) as exc:
        await ContactService().get_or_create_from_client(
            CaptureSession(client),  # type: ignore[arg-type]
            client.id,
        )
    assert exc.value.status_code == 402


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_contacts_api_returns_402(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    user = _make_user(org_id=org)
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    app = FastAPI()
    app.include_router(contacts_router, prefix="/api/v1")

    async def _user() -> User:
        return user

    async def _db():
        yield FlushSession()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post("/api/v1/crm/contacts", json={"first_name": "Ada"})
        blocked = await client.post("/api/v1/crm/contacts", json={"first_name": "Bob"})

    assert ok.status_code == 201
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["code"] == "crm_contacts_limit"
    assert blocked.json()["detail"]["billing_url"] == "/billing"


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_deals_api_returns_402(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    user = _make_user(org_id=org)
    pipe, stage = _seed_pipeline(store, org)
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(deal_service, "_log_event", _noop)
    monkeypatch.setattr(deal_service, "_dispatch_automations", _noop)

    app = FastAPI()
    app.include_router(deals_router, prefix="/api/v1")

    async def _user() -> User:
        return user

    async def _db():
        yield FlushSession()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db

    body = {
        "title": "Deal",
        "pipeline_id": str(pipe.id),
        "stage_id": str(stage.id),
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post("/api/v1/crm/deals", json=body)
        blocked = await client.post(
            "/api/v1/crm/deals",
            json={**body, "title": "Deal 2"},
        )

    assert ok.status_code == 201
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["code"] == "crm_deals_open_limit"


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_automations_api_returns_402(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    user = _make_user(org_id=org)
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    app = FastAPI()
    app.include_router(automations_router, prefix="/api/v1")

    async def _user() -> User:
        return user

    async def _db():
        yield FlushSession()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db

    body = {
        "name": "Rule",
        "trigger_type": "deal_created",
        "actions": [{"type": "add_tag", "tag_name": "x"}],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post("/api/v1/crm/automations", json=body)
        blocked = await client.post(
            "/api/v1/crm/automations",
            json={**body, "name": "Rule 2"},
        )

    assert ok.status_code == 201
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["code"] == "crm_automation_rules_limit"


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_public_inbound_returns_402_on_contact_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store()
    org = uuid.uuid4()
    _seed_pipeline(store, org)
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    await contact_service.create_contact(
        FlushSession(),  # type: ignore[arg-type]
        org,
        CrmContactCreate(first_name="Taken"),
    )

    from app.api.endpoints.crm.deps import verify_crm_api_key
    from app.models.crm.api_key import CrmApiKey
    from app.services.crm.api_key_service import VerifiedCrmApiKey

    app = FastAPI()
    app.include_router(public_leads_router, prefix="/api/v1")

    fake_key = CrmApiKey(
        id=uuid.uuid4(),
        organization_id=org,
        label="test",
        key_hash="x",
        key_prefix="mpai_crm_",
        is_active=True,
        created_at=_now(),
        updated_at=_now(),
    )

    async def _verified() -> VerifiedCrmApiKey:
        return VerifiedCrmApiKey(organization_id=org, api_key=fake_key)

    async def _db():
        yield FlushSession()

    app.dependency_overrides[verify_crm_api_key] = _verified
    app.dependency_overrides[get_db] = _db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/crm/public/leads",
            json={"first_name": "Lead", "phone": "+77001112233"},
        )

    assert resp.status_code == 402
    assert resp.json()["detail"]["billing_url"] == "/billing"


@pytest.mark.crm_quotas
@pytest.mark.asyncio
async def test_quota_service_unit_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store()
    org = uuid.uuid4()
    _bind_repos(monkeypatch, store)
    _limit_free_to_one(monkeypatch)

    svc = QuotaService()
    db = FlushSession()
    await svc.assert_crm_contacts_quota(db, org)  # type: ignore[arg-type]

    store.contacts[uuid.uuid4()] = CrmContact(
        id=uuid.uuid4(),
        organization_id=org,
        first_name="A",
        last_name="",
        custom_fields={},
        created_at=_now(),
        updated_at=_now(),
    )
    with pytest.raises(QuotaExceeded) as exc:
        await svc.assert_crm_contacts_quota(db, org)  # type: ignore[arg-type]
    assert exc.value.code == "crm_contacts_limit"
