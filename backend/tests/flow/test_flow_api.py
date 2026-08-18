"""Step 3.3 — Flow CRUD API: validation + tenant isolation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.endpoints.flow.flows import router as flows_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.flow import Flow
from app.models.users import User
from app.services.flow.flow_crud_service import (
    FlowNotFoundError,
    FlowServiceError,
    FlowCrudService,
    validate_flow_graph,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _trigger_graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        {
            "id": "trigger-1",
            "type": "trigger",
            "position": {"x": 0, "y": 0},
            "data": {"label": "Start"},
        },
        {
            "id": "end-1",
            "type": "end",
            "position": {"x": 200, "y": 0},
            "data": {},
        },
    ]
    edges = [{"id": "e1", "source": "trigger-1", "target": "end-1"}]
    return nodes, edges


def _make_user(*, org_id: uuid.UUID, role: UserRole = UserRole.OWNER) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@flow.test",
        hashed_password="!",
        company_name="Org",
        full_name="Flow Tester",
        company_id=org_id,
        role=role,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


class Store:
    def __init__(self) -> None:
        self.flows: dict[uuid.UUID, Flow] = {}


class FakeSession:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, obj: Any) -> None:
        if isinstance(obj, Flow):
            obj.id = getattr(obj, "id", None) or uuid.uuid4()
            obj.created_at = getattr(obj, "created_at", None) or _now()
            obj.updated_at = getattr(obj, "updated_at", None) or _now()
            obj.is_active = bool(getattr(obj, "is_active", True))
            obj.graph_snapshot = dict(getattr(obj, "graph_snapshot", None) or {})
            obj.nodes = []
            obj.edges = []
            self.store.flows[obj.id] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        obj.updated_at = _now()

    async def delete(self, obj: Any) -> None:
        if isinstance(obj, Flow):
            self.store.flows.pop(obj.id, None)

    async def get(self, model: Any, ident: Any) -> Any:
        if model is Flow:
            return self.store.flows.get(ident)
        return None

    async def execute(self, stmt: Any) -> Any:
        try:
            compiled = stmt.compile(compile_kwargs={"render_postcompile": True})
            sql = str(compiled).lower()
            params = dict(compiled.params or {})
        except Exception:
            sql = str(stmt).lower()
            params = {}

        rows = list(self.store.flows.values())
        org_ids = [v for v in params.values() if isinstance(v, uuid.UUID)]
        if org_ids:
            oid = org_ids[0]
            rows = [r for r in rows if r.organization_id == oid]
        if "is_active" in sql and "true" in sql:
            rows = [r for r in rows if r.is_active]

        class _Result:
            def scalars(self_inner) -> Any:
                class _S:
                    def all(self_s) -> list[Any]:
                        return list(rows)

                return _S()

        return _Result()


def test_validate_rejects_empty_name() -> None:
    with pytest.raises(FlowServiceError, match="name"):
        validate_flow_graph(name="   ", nodes=[], edges=[], require_trigger=False)


def test_validate_rejects_graph_without_trigger() -> None:
    with pytest.raises(FlowServiceError, match="trigger"):
        validate_flow_graph(
            name="Demo",
            nodes=[{"id": "n1", "type": "message", "data": {}}],
            edges=[],
        )


def test_validate_accepts_trigger_graph() -> None:
    nodes, edges = _trigger_graph()
    out_nodes, out_edges = validate_flow_graph(name="Demo", nodes=nodes, edges=edges)
    assert len(out_nodes) == 2
    assert len(out_edges) == 1


@pytest.mark.asyncio
async def test_crud_create_list_update_delete() -> None:
    store = Store()
    db = FakeSession(store)
    service = FlowCrudService()
    org_id = uuid.uuid4()
    nodes, edges = _trigger_graph()

    created = await service.create_flow(
        db, org_id, name="Welcome", nodes=nodes, edges=edges
    )
    assert created.organization_id == org_id
    assert created.graph_snapshot["nodes"][0]["type"] == "trigger"

    listed = await service.list_flows(db, org_id)
    assert len(listed) == 1

    updated = await service.update_flow(
        db,
        created.id,
        org_id,
        name="Welcome v2",
        nodes=nodes,
        edges=edges,
    )
    assert updated.name == "Welcome v2"

    deleted = await service.delete_flow(db, created.id, org_id)
    assert deleted.is_active is False


@pytest.mark.asyncio
async def test_create_without_trigger_raises() -> None:
    service = FlowCrudService()
    db = FakeSession(Store())
    with pytest.raises(FlowServiceError, match="trigger"):
        await service.create_flow(
            db,
            uuid.uuid4(),
            name="Broken",
            nodes=[{"id": "x", "type": "llm", "data": {}}],
            edges=[],
        )


@pytest.mark.asyncio
async def test_tenant_isolation_service_level() -> None:
    store = Store()
    db = FakeSession(store)
    service = FlowCrudService()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    nodes, edges = _trigger_graph()

    flow_a = await service.create_flow(db, org_a, name="A", nodes=nodes, edges=edges)
    await service.create_flow(db, org_b, name="B", nodes=nodes, edges=edges)

    assert len(await service.list_flows(db, org_a)) == 1
    assert len(await service.list_flows(db, org_b)) == 1

    with pytest.raises(FlowNotFoundError):
        await service.get_flow(db, flow_a.id, org_b)

    with pytest.raises(FlowNotFoundError):
        await service.update_flow(db, flow_a.id, org_b, name="Hacked")


@pytest.mark.asyncio
async def test_api_crud_and_validation_and_tenant_isolation() -> None:
    store = Store()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    user_a = _make_user(org_id=org_a)
    user_b = _make_user(org_id=org_b)
    current = {"user": user_a}

    app = FastAPI()
    app.include_router(flows_router, prefix="/api/v1")

    async def _db():
        yield FakeSession(store)

    async def _user():
        return current["user"]

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user

    nodes, edges = _trigger_graph()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Reject graph without trigger
        bad = await client.post(
            "/api/v1/flows",
            json={
                "name": "No trigger",
                "nodes": [{"id": "n1", "type": "condition", "data": {}}],
                "edges": [],
            },
        )
        assert bad.status_code == 400
        assert "trigger" in bad.json()["detail"].lower()

        created = await client.post(
            "/api/v1/flows",
            json={"name": "Org A Flow", "nodes": nodes, "edges": edges},
        )
        assert created.status_code == 201
        flow_id = created.json()["id"]
        assert created.json()["organization_id"] == str(org_a)

        listed = await client.get("/api/v1/flows")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        got = await client.get(f"/api/v1/flows/{flow_id}")
        assert got.status_code == 200
        assert got.json()["name"] == "Org A Flow"

        updated = await client.put(
            f"/api/v1/flows/{flow_id}",
            json={"name": "Renamed", "nodes": nodes, "edges": edges},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Renamed"

        # Org B cannot read/edit Org A flow
        current["user"] = user_b
        forbidden_get = await client.get(f"/api/v1/flows/{flow_id}")
        assert forbidden_get.status_code == 404

        forbidden_put = await client.put(
            f"/api/v1/flows/{flow_id}",
            json={"name": "Stolen", "nodes": nodes, "edges": edges},
        )
        assert forbidden_put.status_code == 404

        # Soft delete as Org A
        current["user"] = user_a
        deleted = await client.delete(f"/api/v1/flows/{flow_id}")
        assert deleted.status_code == 200
        assert deleted.json()["is_active"] is False
