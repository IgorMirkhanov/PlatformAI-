"""Native CRM Phase C step 1 — analytics / funnel / forecast."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList

from app.api.endpoints.crm.analytics import router as analytics_router
from app.core.database import get_db
from app.core.rbac import get_current_user
from app.models.core_models import UserRole
from app.models.crm.deal import CrmDeal, DealStatus
from app.models.crm.pipeline import CrmPipeline
from app.models.crm.stage import CrmStage
from app.models.users import User
from app.services.crm.crm_analytics_service import CrmAnalyticsService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_user(*, org_id: uuid.UUID, role: UserRole = UserRole.OWNER) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=f"{uid.hex[:8]}@crm.test",
        hashed_password="!",
        company_name="Org",
        full_name="CRM Analytics Tester",
        company_id=org_id,
        role=role,
        is_superadmin=False,
        timezone="Asia/Almaty",
    )


class Store:
    def __init__(self) -> None:
        self.pipelines: dict[uuid.UUID, CrmPipeline] = {}
        self.stages: dict[uuid.UUID, CrmStage] = {}
        self.deals: dict[uuid.UUID, CrmDeal] = {}


def _seed_pipeline(
    store: Store,
    org_id: uuid.UUID,
    *,
    name: str = "Sales",
) -> tuple[CrmPipeline, CrmStage, CrmStage, CrmStage]:
    pipeline = CrmPipeline(
        id=uuid.uuid4(),
        organization_id=org_id,
        name=name,
        position=0,
        is_default=True,
        created_at=_now(),
        updated_at=_now(),
    )
    s1 = CrmStage(
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
    s2 = CrmStage(
        id=uuid.uuid4(),
        organization_id=org_id,
        pipeline_id=pipeline.id,
        name="Negotiation",
        position=1,
        color=None,
        is_won=False,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    s3 = CrmStage(
        id=uuid.uuid4(),
        organization_id=org_id,
        pipeline_id=pipeline.id,
        name="Won",
        position=2,
        color=None,
        is_won=True,
        is_lost=False,
        created_at=_now(),
        updated_at=_now(),
    )
    store.pipelines[pipeline.id] = pipeline
    store.stages[s1.id] = s1
    store.stages[s2.id] = s2
    store.stages[s3.id] = s3
    return pipeline, s1, s2, s3


def _add_deal(
    store: Store,
    *,
    org_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    stage_id: uuid.UUID,
    amount: str | Decimal,
    status: DealStatus = DealStatus.OPEN,
    assigned_user_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> CrmDeal:
    deal = CrmDeal(
        id=uuid.uuid4(),
        organization_id=org_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
        title=f"Deal {amount}",
        amount=Decimal(str(amount)),
        currency="KZT",
        status=status,
        assigned_user_id=assigned_user_id,
        custom_fields={},
        created_at=created_at or _now(),
        updated_at=_now(),
        closed_at=closed_at,
    )
    store.deals[deal.id] = deal
    return deal


def _eq_value(clause: ColumnElement[Any] | None, column_key: str) -> Any:
    """Extract ``column == bind`` value from a WHERE tree (test helper)."""
    if clause is None:
        return None
    if isinstance(clause, BooleanClauseList):
        for child in clause.clauses:
            found = _eq_value(child, column_key)
            if found is not None:
                return found
        return None
    if isinstance(clause, BinaryExpression):
        left, right = clause.left, clause.right
        for col, other in ((left, right), (right, left)):
            col_key = getattr(col, "key", None) or getattr(col, "name", None)
            if col_key == column_key:
                if isinstance(other, BindParameter):
                    return other.value
                return other
        return None
    return None


def _labels(stmt: Any) -> set[str]:
    return {getattr(c, "name", None) or getattr(c, "key", None) for c in stmt.selected_columns}


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def one(self) -> Any:
        if len(self._rows) != 1:
            raise AssertionError(f"Expected 1 row, got {len(self._rows)}")
        return self._rows[0]


class AnalyticsSession:
    """
    In-memory AsyncSession stand-in that applies the same aggregates as the
    SQL in ``CrmAnalyticsService`` (tenant-filtered).
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        self.captured_stmts: list[Any] = []

    async def scalar(self, stmt: Any) -> Any:
        self.captured_stmts.append(stmt)
        org_id = _eq_value(stmt.whereclause, "organization_id")
        pipeline_id = _eq_value(stmt.whereclause, "id")
        if org_id is None or pipeline_id is None:
            return None
        row = self.store.pipelines.get(pipeline_id)
        if row is None or row.organization_id != org_id:
            return None
        return row.id

    async def execute(self, stmt: Any) -> _Result:
        self.captured_stmts.append(stmt)
        labels = _labels(stmt)

        if "deal_count" in labels and "amount_sum" in labels:
            return _Result(self._funnel_stages(stmt))
        if "total_deals" in labels and "won_deals" in labels:
            return _Result([self._funnel_totals(stmt)])
        if "won_count" in labels and "lost_count" in labels and "revenue" in labels:
            return _Result(self._performance(stmt))
        if "open_deal_count" in labels and "forecast_amount" in labels:
            return _Result([self._forecast(stmt)])
        raise AssertionError(f"Unhandled analytics statement labels={labels}")

    def _funnel_stages(self, stmt: Any) -> list[Any]:
        org_id = _eq_value(stmt.whereclause, "organization_id")
        pipeline_id = _eq_value(stmt.whereclause, "pipeline_id")
        stages = sorted(
            [
                s
                for s in self.store.stages.values()
                if s.organization_id == org_id and s.pipeline_id == pipeline_id
            ],
            key=lambda s: s.position,
        )
        rows = []
        for stage in stages:
            deals = [
                d
                for d in self.store.deals.values()
                if d.organization_id == org_id
                and d.pipeline_id == pipeline_id
                and d.stage_id == stage.id
            ]
            rows.append(
                SimpleNamespace(
                    stage_id=stage.id,
                    stage_name=stage.name,
                    position=stage.position,
                    deal_count=len(deals),
                    amount_sum=sum((d.amount for d in deals), Decimal("0.00")),
                )
            )
        return rows

    def _funnel_totals(self, stmt: Any) -> Any:
        org_id = _eq_value(stmt.whereclause, "organization_id")
        pipeline_id = _eq_value(stmt.whereclause, "pipeline_id")
        deals = [
            d
            for d in self.store.deals.values()
            if d.organization_id == org_id and d.pipeline_id == pipeline_id
        ]
        won = sum(1 for d in deals if d.status == DealStatus.WON)
        return SimpleNamespace(total_deals=len(deals), won_deals=won)

    def _performance(self, stmt: Any) -> list[Any]:
        org_id = _eq_value(stmt.whereclause, "organization_id")
        closed = [
            d
            for d in self.store.deals.values()
            if d.organization_id == org_id
            and d.status in (DealStatus.WON, DealStatus.LOST)
        ]
        by_user: dict[uuid.UUID | None, list[CrmDeal]] = {}
        for d in closed:
            by_user.setdefault(d.assigned_user_id, []).append(d)
        rows = []
        for user_id, deals in by_user.items():
            won = [d for d in deals if d.status == DealStatus.WON]
            lost = [d for d in deals if d.status == DealStatus.LOST]
            rows.append(
                SimpleNamespace(
                    assigned_user_id=user_id,
                    won_count=len(won),
                    lost_count=len(lost),
                    revenue=sum((d.amount for d in won), Decimal("0.00")),
                )
            )
        rows.sort(key=lambda r: r.revenue, reverse=True)
        return rows

    def _forecast(self, stmt: Any) -> Any:
        org_id = _eq_value(stmt.whereclause, "organization_id")
        opens = [
            d
            for d in self.store.deals.values()
            if d.organization_id == org_id and d.status == DealStatus.OPEN
        ]
        return SimpleNamespace(
            open_deal_count=len(opens),
            forecast_amount=sum((d.amount for d in opens), Decimal("0.00")),
        )


@pytest.fixture
def org_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def org_b() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def analytics_store(org_a: uuid.UUID, org_b: uuid.UUID) -> Store:
    store = Store()
    pipe_a, new_a, nego_a, won_a = _seed_pipeline(store, org_a)
    pipe_b, new_b, _, _ = _seed_pipeline(store, org_b, name="Other tenant")

    mgr1 = uuid.uuid4()
    mgr2 = uuid.uuid4()

    _add_deal(store, org_id=org_a, pipeline_id=pipe_a.id, stage_id=new_a.id, amount="100")
    _add_deal(store, org_id=org_a, pipeline_id=pipe_a.id, stage_id=new_a.id, amount="50")
    _add_deal(store, org_id=org_a, pipeline_id=pipe_a.id, stage_id=nego_a.id, amount="200")
    _add_deal(
        store,
        org_id=org_a,
        pipeline_id=pipe_a.id,
        stage_id=won_a.id,
        amount="500",
        status=DealStatus.WON,
        assigned_user_id=mgr1,
        closed_at=_now(),
    )
    _add_deal(
        store,
        org_id=org_a,
        pipeline_id=pipe_a.id,
        stage_id=nego_a.id,
        amount="80",
        status=DealStatus.LOST,
        assigned_user_id=mgr1,
        closed_at=_now(),
    )
    _add_deal(
        store,
        org_id=org_a,
        pipeline_id=pipe_a.id,
        stage_id=won_a.id,
        amount="300",
        status=DealStatus.WON,
        assigned_user_id=mgr2,
        closed_at=_now(),
    )

    _add_deal(store, org_id=org_b, pipeline_id=pipe_b.id, stage_id=new_b.id, amount="99999")
    _add_deal(
        store,
        org_id=org_b,
        pipeline_id=pipe_b.id,
        stage_id=new_b.id,
        amount="88888",
        status=DealStatus.WON,
        assigned_user_id=uuid.uuid4(),
        closed_at=_now(),
    )

    store._pipe_a = pipe_a  # type: ignore[attr-defined]
    store._mgr1 = mgr1  # type: ignore[attr-defined]
    store._mgr2 = mgr2  # type: ignore[attr-defined]
    return store


@pytest.mark.asyncio
async def test_get_pipeline_funnel_aggregates(
    analytics_store: Store, org_a: uuid.UUID
) -> None:
    svc = CrmAnalyticsService()
    session = AnalyticsSession(analytics_store)
    pipe_id = analytics_store._pipe_a.id  # type: ignore[attr-defined]

    result = await svc.get_pipeline_funnel(session, org_a, pipe_id)  # type: ignore[arg-type]

    by_name = {s.stage_name: s for s in result.stages}
    assert by_name["New"].deal_count == 2
    assert by_name["New"].amount_sum == Decimal("150")
    assert by_name["Negotiation"].deal_count == 2
    assert by_name["Negotiation"].amount_sum == Decimal("280")
    assert by_name["Won"].deal_count == 2
    assert by_name["Won"].amount_sum == Decimal("800")
    assert result.total_deals == 6
    assert result.won_deals == 2
    assert result.conversion_rate == pytest.approx(2 / 6)


@pytest.mark.asyncio
async def test_get_manager_performance_aggregates(
    analytics_store: Store, org_a: uuid.UUID
) -> None:
    svc = CrmAnalyticsService()
    session = AnalyticsSession(analytics_store)
    result = await svc.get_manager_performance(session, org_a)  # type: ignore[arg-type]

    mgr1 = analytics_store._mgr1  # type: ignore[attr-defined]
    mgr2 = analytics_store._mgr2  # type: ignore[attr-defined]
    by_user = {row.assigned_user_id: row for row in result.items}

    assert by_user[mgr1].won_count == 1
    assert by_user[mgr1].lost_count == 1
    assert by_user[mgr1].revenue == Decimal("500")
    assert by_user[mgr2].won_count == 1
    assert by_user[mgr2].lost_count == 0
    assert by_user[mgr2].revenue == Decimal("300")
    assert result.items[0].assigned_user_id == mgr1


@pytest.mark.asyncio
async def test_get_revenue_forecast_aggregates(
    analytics_store: Store, org_a: uuid.UUID
) -> None:
    svc = CrmAnalyticsService()
    session = AnalyticsSession(analytics_store)
    result = await svc.get_revenue_forecast(session, org_a)  # type: ignore[arg-type]

    assert result.open_deal_count == 3
    assert result.forecast_amount == Decimal("350")


@pytest.mark.asyncio
async def test_analytics_tenant_isolation(
    analytics_store: Store, org_a: uuid.UUID, org_b: uuid.UUID
) -> None:
    svc = CrmAnalyticsService()
    session = AnalyticsSession(analytics_store)
    pipe_a = analytics_store._pipe_a.id  # type: ignore[attr-defined]

    funnel_a = await svc.get_pipeline_funnel(session, org_a, pipe_a)  # type: ignore[arg-type]
    forecast_a = await svc.get_revenue_forecast(session, org_a)  # type: ignore[arg-type]
    perf_a = await svc.get_manager_performance(session, org_a)  # type: ignore[arg-type]

    assert funnel_a.total_deals == 6
    assert all(s.amount_sum < Decimal("10000") for s in funnel_a.stages)
    assert forecast_a.forecast_amount == Decimal("350")
    assert sum(r.revenue for r in perf_a.items) == Decimal("800")

    forecast_b = await svc.get_revenue_forecast(session, org_b)  # type: ignore[arg-type]
    assert forecast_b.open_deal_count == 1
    assert forecast_b.forecast_amount == Decimal("99999")

    for stmt in session.captured_stmts:
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "organization_id" in compiled


@pytest.mark.asyncio
async def test_funnel_unknown_pipeline_404(org_a: uuid.UUID) -> None:
    from app.services.crm.crm_analytics_service import CrmAnalyticsServiceError

    svc = CrmAnalyticsService()
    session = AnalyticsSession(Store())
    with pytest.raises(CrmAnalyticsServiceError) as exc_info:
        await svc.get_pipeline_funnel(session, org_a, uuid.uuid4())  # type: ignore[arg-type]
    assert exc_info.value.status_code == 404


def _build_app(user: User, session: AnalyticsSession) -> FastAPI:
    app = FastAPI()
    app.include_router(analytics_router, prefix="/api/v1")

    async def _override_user() -> User:
        return user

    async def _override_db():
        yield session

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.mark.asyncio
async def test_analytics_endpoints_owner(
    analytics_store: Store, org_a: uuid.UUID
) -> None:
    user = _make_user(org_id=org_a, role=UserRole.OWNER)
    session = AnalyticsSession(analytics_store)
    app = _build_app(user, session)
    pipe_id = analytics_store._pipe_a.id  # type: ignore[attr-defined]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        funnel = await client.get(
            "/api/v1/crm/analytics/funnel",
            params={"pipeline_id": str(pipe_id)},
        )
        perf = await client.get("/api/v1/crm/analytics/performance")
        forecast = await client.get("/api/v1/crm/analytics/forecast")

    assert funnel.status_code == 200
    body = funnel.json()
    assert body["total_deals"] == 6
    assert body["won_deals"] == 2
    assert abs(body["conversion_rate"] - (2 / 6)) < 1e-9
    new_stage = next(s for s in body["stages"] if s["stage_name"] == "New")
    assert new_stage["deal_count"] == 2
    assert Decimal(str(new_stage["amount_sum"])) == Decimal("150")

    assert perf.status_code == 200
    assert len(perf.json()["items"]) == 2

    assert forecast.status_code == 200
    assert forecast.json()["open_deal_count"] == 3
    assert Decimal(str(forecast.json()["forecast_amount"])) == Decimal("350")


@pytest.mark.asyncio
async def test_analytics_endpoints_forbid_operator(org_a: uuid.UUID) -> None:
    user = _make_user(org_id=org_a, role=UserRole.OPERATOR)
    session = AnalyticsSession(Store())
    app = _build_app(user, session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/crm/analytics/forecast")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_usage_metric_types_include_crm_events() -> None:
    from app.models.saas_metering import UsageMetricType

    assert UsageMetricType.DEAL_CREATED.value == "DEAL_CREATED"
    assert UsageMetricType.DEAL_WON.value == "DEAL_WON"
    assert UsageMetricType.DEAL_LOST.value == "DEAL_LOST"
    assert UsageMetricType.TASK_COMPLETED.value == "TASK_COMPLETED"


@pytest.mark.asyncio
async def test_record_crm_usage_event_skips_without_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.saas_metering import UsageMetricType
    from app.services.crm import crm_usage_events

    called = {"n": 0}

    async def _boom(*_a: Any, **_k: Any) -> None:
        called["n"] += 1

    monkeypatch.setattr(
        crm_usage_events.usage_service,
        "record_and_debit",
        _boom,
    )
    await crm_usage_events.record_crm_usage_event(
        SimpleNamespace(),  # type: ignore[arg-type]
        organization_id=uuid.uuid4(),
        metric_type=UsageMetricType.DEAL_CREATED,
        user_id=None,
    )
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_record_crm_usage_event_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.saas_metering import UsageMetricType
    from app.services.crm import crm_usage_events

    captured: dict[str, Any] = {}

    async def _record(*_a: Any, **kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(
        crm_usage_events.usage_service,
        "record_and_debit",
        _record,
    )
    uid = uuid.uuid4()
    org = uuid.uuid4()
    await crm_usage_events.record_crm_usage_event(
        SimpleNamespace(),  # type: ignore[arg-type]
        organization_id=org,
        metric_type=UsageMetricType.TASK_COMPLETED,
        user_id=uid,
        meta={"activity_id": "x"},
    )
    assert captured["user_id"] == uid
    assert captured["organization_id"] == org
    assert captured["metric_type"] == UsageMetricType.TASK_COMPLETED
    assert captured["debit_wallet"] is False
    assert captured["quantity"] == 1
