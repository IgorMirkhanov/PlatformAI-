"""Native CRM Phase B step 1 — automation rules CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models.crm.automation_rule import AutomationTriggerType, CrmAutomationRule
from app.schemas.crm.automations import CrmAutomationRuleCreate, CrmAutomationRuleUpdate
from app.services.crm.automation_rule_service import (
    AutomationRuleService,
    AutomationRuleServiceError,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self) -> None:
        self.rules: dict[uuid.UUID, CrmAutomationRule] = {}


class FlushSession:
    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeAutomationRuleRepo:
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

    async def get(self, entity_id: uuid.UUID) -> CrmAutomationRule | None:
        row = self.store.rules.get(entity_id)
        if row is None or row.organization_id != self.organization_id:
            return None
        return row

    async def list_filtered(
        self,
        *,
        is_active: bool | None = None,
        trigger_type: AutomationTriggerType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CrmAutomationRule]:
        rows = [
            r
            for r in self.store.rules.values()
            if r.organization_id == self.organization_id
            and (is_active is None or r.is_active is is_active)
            and (trigger_type is None or r.trigger_type == trigger_type)
        ]
        rows = sorted(rows, key=lambda r: (r.created_at, r.name), reverse=True)
        return rows[offset : offset + limit]

    async def count_filtered(
        self,
        *,
        is_active: bool | None = None,
        trigger_type: AutomationTriggerType | None = None,
    ) -> int:
        return len(
            await self.list_filtered(
                is_active=is_active,
                trigger_type=trigger_type,
                limit=10_000,
                offset=0,
            )
        )

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

    async def delete(self, entity: CrmAutomationRule) -> None:
        self.store.rules.pop(entity.id, None)


def _bind(store: Store) -> AutomationRuleService:
    service = AutomationRuleService()
    service._repo = lambda _db, org: FakeAutomationRuleRepo(store, org)  # type: ignore[method-assign]
    return service


def _create_payload(
    *,
    name: str = "Move on stage enter",
    trigger_type: AutomationTriggerType = AutomationTriggerType.STAGE_ENTERED,
    is_active: bool = True,
) -> CrmAutomationRuleCreate:
    return CrmAutomationRuleCreate(
        name=name,
        is_active=is_active,
        trigger_type=trigger_type,
        trigger_config={"stage_id": str(uuid.uuid4())},
        conditions={"op": "and", "rules": []},
        actions=[{"type": "move_stage", "stage_id": str(uuid.uuid4())}],
    )


@pytest.mark.asyncio
async def test_automation_rule_crud() -> None:
    store = Store()
    service = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()

    created = await service.create_rule(db, org, _create_payload())  # type: ignore[arg-type]
    assert created.name == "Move on stage enter"
    assert created.trigger_type == AutomationTriggerType.STAGE_ENTERED
    assert created.is_active is True
    assert created.organization_id == org
    assert created.actions[0]["type"] == "move_stage"

    listed = await service.list_rules(db, org)  # type: ignore[arg-type]
    assert listed.total == 1
    assert listed.items[0].id == created.id

    fetched = await service.get_rule(db, org, created.id)  # type: ignore[arg-type]
    assert fetched.id == created.id

    updated = await service.update_rule(
        db,  # type: ignore[arg-type]
        org,
        created.id,
        CrmAutomationRuleUpdate(name="Renamed", is_active=False),
    )
    assert updated.name == "Renamed"
    assert updated.is_active is False

    await service.delete_rule(db, org, created.id)  # type: ignore[arg-type]
    with pytest.raises(AutomationRuleServiceError) as exc:
        await service.get_rule(db, org, created.id)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_tenant_isolation_automation_rules() -> None:
    store = Store()
    service = _bind(store)
    db = FlushSession()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    created = await service.create_rule(
        db,  # type: ignore[arg-type]
        org_a,
        _create_payload(name="Org A only"),
    )

    listed_b = await service.list_rules(db, org_b)  # type: ignore[arg-type]
    assert listed_b.total == 0
    assert listed_b.items == []

    with pytest.raises(AutomationRuleServiceError) as exc:
        await service.get_rule(db, org_b, created.id)  # type: ignore[arg-type]
    assert exc.value.status_code == 404

    with pytest.raises(AutomationRuleServiceError) as exc_upd:
        await service.update_rule(
            db,  # type: ignore[arg-type]
            org_b,
            created.id,
            CrmAutomationRuleUpdate(is_active=False),
        )
    assert exc_upd.value.status_code == 404

    with pytest.raises(AutomationRuleServiceError) as exc_del:
        await service.delete_rule(db, org_b, created.id)  # type: ignore[arg-type]
    assert exc_del.value.status_code == 404

    still_there = await service.get_rule(db, org_a, created.id)  # type: ignore[arg-type]
    assert still_there.id == created.id


@pytest.mark.asyncio
async def test_filter_by_is_active_and_trigger_type() -> None:
    store = Store()
    service = _bind(store)
    db = FlushSession()
    org = uuid.uuid4()

    await service.create_rule(
        db,  # type: ignore[arg-type]
        org,
        _create_payload(
            name="Active stage",
            trigger_type=AutomationTriggerType.STAGE_ENTERED,
            is_active=True,
        ),
    )
    await service.create_rule(
        db,  # type: ignore[arg-type]
        org,
        _create_payload(
            name="Inactive stage",
            trigger_type=AutomationTriggerType.STAGE_ENTERED,
            is_active=False,
        ),
    )
    await service.create_rule(
        db,  # type: ignore[arg-type]
        org,
        _create_payload(
            name="Active deal created",
            trigger_type=AutomationTriggerType.DEAL_CREATED,
            is_active=True,
        ),
    )

    active_only = await service.list_rules(db, org, is_active=True)  # type: ignore[arg-type]
    assert active_only.total == 2
    assert {r.name for r in active_only.items} == {"Active stage", "Active deal created"}

    stage_only = await service.list_rules(
        db,  # type: ignore[arg-type]
        org,
        trigger_type=AutomationTriggerType.STAGE_ENTERED,
    )
    assert stage_only.total == 2
    assert {r.name for r in stage_only.items} == {"Active stage", "Inactive stage"}

    active_stage = await service.list_rules(
        db,  # type: ignore[arg-type]
        org,
        is_active=True,
        trigger_type=AutomationTriggerType.STAGE_ENTERED,
    )
    assert active_stage.total == 1
    assert active_stage.items[0].name == "Active stage"

    by_trigger = await service.get_active_rules_by_trigger(
        db,  # type: ignore[arg-type]
        org,
        AutomationTriggerType.STAGE_ENTERED,
    )
    assert len(by_trigger) == 1
    assert by_trigger[0].name == "Active stage"
    assert by_trigger[0].is_active is True


def test_migration_035_exists() -> None:
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "035_crm_automation_rules.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "crm_automation_rules" in text
    assert "034_crm_settings" in text
    assert "trigger_config" in text
    assert "conditions" in text
    assert "actions" in text
    assert "JSONB" in text
    assert 'ondelete="CASCADE"' in text
    assert "ck_crm_automation_rules_trigger_type" in text


def test_no_direct_selects_outside_repos() -> None:
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    pattern = re.compile(r"select\(\s*CrmAutomationRule\b")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if "repositories" in path.parts and "crm" in path.parts:
            continue
        if "models" in path.parts and "crm" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_automation_rule_repo_extends_base() -> None:
    from app.repositories.crm.automation_rule_repository import AutomationRuleRepository
    from app.repositories.crm.base_crm_repository import BaseCrmRepository

    assert issubclass(AutomationRuleRepository, BaseCrmRepository)
    assert AutomationRuleRepository.model is CrmAutomationRule


def test_automations_router_registered() -> None:
    from app.api.endpoints.crm import automations_router
    from app.api.router import api_v1_router

    assert automations_router.prefix == "/crm/automations"
    included = [
        getattr(r, "original_router", None)
        for r in api_v1_router.routes
        if getattr(r, "original_router", None) is not None
    ]
    assert automations_router in included
