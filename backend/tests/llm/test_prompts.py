"""Step 1.4 — Prompt template CRUD, Jinja2 render, tenant isolation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from app.models.llm.prompt_template import PromptTemplate
from app.services.llm.prompt_service import (
    PromptNotFoundError,
    PromptTemplateService,
    PromptVariableMissingError,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self) -> None:
        self.templates: dict[uuid.UUID, PromptTemplate] = {}


class FakeSession:
    """Minimal async session for PromptTemplateService unit tests."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, obj: Any) -> None:
        if isinstance(obj, PromptTemplate):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            obj.updated_at = getattr(obj, "updated_at", None) or _now()
            obj.version = int(getattr(obj, "version", None) or 1)
            obj.is_active = bool(getattr(obj, "is_active", True))
            self.store.templates[obj.id] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        obj.updated_at = _now()

    async def delete(self, obj: Any) -> None:
        if isinstance(obj, PromptTemplate):
            self.store.templates.pop(obj.id, None)

    async def get(self, model: Any, ident: Any) -> Any:
        if model is PromptTemplate:
            return self.store.templates.get(ident)
        return None

    async def execute(self, stmt: Any) -> Any:
        rows = self._filter(stmt)

        class _Result:
            def scalars(self_inner) -> Any:
                class _S:
                    def all(self_s) -> list[Any]:
                        return list(rows)

                return _S()

            def scalar_one_or_none(self_inner) -> Any:
                return rows[0] if rows else None

        return _Result()

    def _filter(self, stmt: Any) -> list[PromptTemplate]:
        try:
            compiled = stmt.compile(compile_kwargs={"render_postcompile": True})
            sql = str(compiled).lower()
            params = dict(compiled.params or {})
        except Exception:
            sql = str(stmt).lower()
            params = {}

        values = list(params.values())
        rows = list(self.store.templates.values())

        # Conflict / get-by-name style filters.
        names = [v for v in values if isinstance(v, str)]
        org_ids = [v for v in values if isinstance(v, uuid.UUID)]
        bools = [v for v in values if isinstance(v, bool)]
        template_ids = [
            v
            for v in values
            if isinstance(v, uuid.UUID) and v in self.store.templates
        ]

        if "organization_id is null" in sql or "organization_id is none" in sql:
            rows = [r for r in rows if r.organization_id is None]
        elif org_ids:
            oid = org_ids[0]
            # list with OR global: keep org + global when both appear in SQL.
            if "is null" in sql or "is none" in sql:
                rows = [
                    r
                    for r in rows
                    if r.organization_id == oid or r.organization_id is None
                ]
            else:
                rows = [r for r in rows if r.organization_id == oid]

        if names:
            # Prefer exact name match when present.
            name = names[0]
            named = [r for r in rows if r.name == name]
            if named or "prompt_templates.name" in sql or " name " in f" {sql} ":
                rows = named if named or name in {r.name for r in self.store.templates.values()} else rows
                if named:
                    rows = named

        if template_ids and "!=" in sql or "<>" in sql:
            exclude = template_ids[0]
            rows = [r for r in rows if r.id != exclude]

        if bools and "is_active" in sql:
            # is_active.is_(True) compiles with true literal.
            rows = [r for r in rows if r.is_active is True]

        # Stable ordering for list
        rows.sort(key=lambda r: (r.name, -int(r.version)))
        return rows


@pytest.mark.asyncio
async def test_create_and_render_with_variables() -> None:
    store = Store()
    db = FakeSession(store)
    org_id = uuid.uuid4()
    service = PromptTemplateService()

    template = await service.create(
        db,  # type: ignore[arg-type]
        org_id,
        name="support_bot_system",
        content=(
            "Привет, {{ contact.name }}! "
            "Твоя заявка на сумму {{ deal.amount }} принята."
        ),
        description="Support greeting",
        created_by_id=uuid.uuid4(),
    )
    assert template.version == 1
    assert template.organization_id == org_id

    result = await service.render_template(
        db,  # type: ignore[arg-type]
        org_id,
        {
            "contact": {"name": "Айгерим"},
            "deal": {"amount": "150000"},
        },
        name="support_bot_system",
    )
    assert "Айгерим" in result["rendered"]
    assert "150000" in result["rendered"]
    assert result["version"] == 1


@pytest.mark.asyncio
async def test_update_increments_version() -> None:
    store = Store()
    db = FakeSession(store)
    org_id = uuid.uuid4()
    service = PromptTemplateService()

    template = await service.create(
        db,  # type: ignore[arg-type]
        org_id,
        name="sales_intro",
        content="Hello {{ name }}",
    )
    assert template.version == 1

    updated = await service.update(
        db,  # type: ignore[arg-type]
        template.id,
        org_id,
        content="Hello {{ name }}, welcome!",
    )
    assert updated.version == 2
    assert "welcome" in updated.content

    updated2 = await service.update(
        db,  # type: ignore[arg-type]
        template.id,
        org_id,
        description="v3 meta",
    )
    assert updated2.version == 3


@pytest.mark.asyncio
async def test_render_missing_variable_raises() -> None:
    store = Store()
    db = FakeSession(store)
    org_id = uuid.uuid4()
    service = PromptTemplateService()

    await service.create(
        db,  # type: ignore[arg-type]
        org_id,
        name="needs_vars",
        content="Hi {{ contact.name }}, deal={{ deal.amount }}",
    )

    with pytest.raises(PromptVariableMissingError) as exc_info:
        await service.render_template(
            db,  # type: ignore[arg-type]
            org_id,
            {"contact": {"name": "Only Contact"}},
            name="needs_vars",
        )
    assert exc_info.value.variable == "deal"
    assert exc_info.value.status_code == 422

    # Nested missing attribute after top-level present.
    with pytest.raises(PromptVariableMissingError):
        service.render_content(
            "Hi {{ contact.name }}",
            {"contact": {}},
            template_name="inline",
        )


@pytest.mark.asyncio
async def test_tenant_isolation_org_a_cannot_see_org_b() -> None:
    store = Store()
    db = FakeSession(store)
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    service = PromptTemplateService()

    await service.create(
        db,  # type: ignore[arg-type]
        org_a,
        name="private_a",
        content="Org A only {{ x }}",
    )
    tpl_b = await service.create(
        db,  # type: ignore[arg-type]
        org_b,
        name="private_b",
        content="Org B only {{ x }}",
    )

    listed_a = await service.list_templates(
        db,  # type: ignore[arg-type]
        org_a,
        include_global=False,
    )
    assert [t.name for t in listed_a] == ["private_a"]

    with pytest.raises(PromptNotFoundError):
        await service.get_by_id(db, tpl_b.id, org_a)  # type: ignore[arg-type]

    with pytest.raises(PromptNotFoundError):
        await service.get_by_name(db, "private_b", org_a)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_delete_deactivates_and_bumps_version() -> None:
    store = Store()
    db = FakeSession(store)
    org_id = uuid.uuid4()
    service = PromptTemplateService()
    tpl = await service.create(
        db,  # type: ignore[arg-type]
        org_id,
        name="to_retire",
        content="bye {{ user }}",
    )
    await service.delete(db, tpl.id, org_id)  # type: ignore[arg-type]
    stored = store.templates[tpl.id]
    assert stored.is_active is False
    assert stored.version == 2
