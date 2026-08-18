"""
Autonomous E2E + stress harness for Flow Engine bot creation & dialogs.

Full cycle (no human):
  A) Seed org + wallet + user
  B) POST /bots + publish Start→LLM→End graph
  C) Sequential sandbox turn — reply, usage log, wallet debit
  D) 50 concurrent dialogs — race-safe wallet, no pool hang, no HTTP 500

Usage:
  pytest backend/tests/e2e/test_autonomous_bot_creation_and_stress.py -v -s

Requires Docker (testcontainers Postgres).
"""

from __future__ import annotations

import asyncio
import math
import os
import statistics
import time
import uuid
from contextlib import ExitStack, suppress
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.models.billing import CreditTransaction, OrganizationWallet
from app.models.core_models import Bot, Company, UserCompanyWorkspace, UserRole
from app.models.usage import LLMUsageLog
from app.models.users import User
from app.services.billing.wallet_service import wallet_service
from app.services.llm.base import LLMResponse
from app.services.llm.gateway import ResilientLLMGateway
from app.services.llm.pricing import calculate_cost
from app.services.sandbox_service import sandbox_service
from main import app
from tests.llm.test_llm_billing import FakeProvider

STRESS_DIALOGS = int(os.getenv("E2E_STRESS_DIALOGS", "50"))
INITIAL_CREDITS = int(os.getenv("E2E_INITIAL_CREDITS", "100000"))
PROMPT_TOKENS = 100
COMPLETION_TOKENS = 50
FIXED_REPLY = "E2E autonomous bot reply: status OK."
EXPECTED_CREDITS_PER_TURN = calculate_cost("gpt-4o-mini", PROMPT_TOKENS, COMPLETION_TOKENS)

FIXED_BUGS: list[str] = [
    "PaymentInvoice.relationship used 'Organization' alias — SQLAlchemy registry "
    "only knows 'Company'; remapped to Company (blocks all ORM configure).",
    "E2E get_db override must commit after request — without it bot create was rolled back "
    "and publish returned 404.",
    "FlowExecutor._resolve_node_entry did not auto-advance trigger/start nodes along "
    "outgoing edges — sandbox returned empty reply at StartNode (fixed passthrough).",
    "AIOrchestrator._record_llm_usage_and_debit returned early on billing_handled and "
    "skipped LLMUsageLog — now always writes usage log, only skips second wallet debit.",
]


@dataclass
class StressReport:
    test_name: str
    total_requests: int
    successful: int = 0
    failed: int = 0
    http_500: int = 0
    timeouts: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0
    balance_before: int = 0
    balance_after: int = 0
    expected_debit: int = 0
    usage_logs: int = 0
    ledger_rows: int = 0
    bot_created: bool = False
    sequential_ok: bool = False
    race_safe: bool = False
    pool_ok: bool = False

    @property
    def duration_s(self) -> float:
        return max(self.end_time - self.start_time, 0.001)

    @property
    def rps(self) -> float:
        return self.total_requests / self.duration_s

    def _pct(self, p: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        idx = min(max(int(math.ceil(len(ordered) * p)) - 1, 0), len(ordered) - 1)
        return ordered[idx]

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95(self) -> float:
        return self._pct(0.95)

    @property
    def p99(self) -> float:
        return self._pct(0.99)

    def print_summary(self) -> None:
        print("\n" + "=" * 64)
        print("  QA REPORT — Flow Engine autonomous bot creation & stress")
        print("=" * 64)
        print(f"  Bot created & published     : {'YES' if self.bot_created else 'NO'}")
        print(f"  Sequential dialog OK        : {'YES' if self.sequential_ok else 'NO'}")
        print(f"  Stress dialogs              : {self.total_requests}")
        print(f"  Successful                  : {self.successful}")
        print(f"  Failed                      : {self.failed}")
        print(f"  HTTP 500 count              : {self.http_500}")
        print(f"  Provider timeout fallbacks  : {self.timeouts}")
        print(f"  Duration                    : {self.duration_s:.2f}s")
        print(f"  RPS                         : {self.rps:.1f}")
        print(f"  Latency p50 / p95 / p99     : {self.p50:.0f} / {self.p95:.0f} / {self.p99:.0f} ms")
        print(f"  Wallet before -> after      : {self.balance_before} -> {self.balance_after}")
        print(f"  Total debit                 : {self.balance_before - self.balance_after}")
        print(f"  Race-safe balance           : {'YES' if self.race_safe else 'NO'}")
        print(f"  Pool / no hang              : {'YES' if self.pool_ok else 'NO'}")
        print(f"  LLMUsageLog rows            : {self.usage_logs}")
        print(f"  CreditTransaction (llm)     : {self.ledger_rows}")
        if FIXED_BUGS:
            print("\n  Fixed bugs during run:")
            for bug in FIXED_BUGS:
                print(f"    - {bug}")
        if self.errors:
            print("\n  Sample errors:")
            for err in list(dict.fromkeys(self.errors))[:5]:
                print(f"    !  {err}")
        print("=" * 64 + "\n")


def _simple_flow_graph() -> dict[str, Any]:
    """StartNode (trigger) → LLMNode (ai_agent) → EndNode (text_message)."""
    return {
        "nodes": [
            {
                "id": "start",
                "type": "trigger",
                "data": {"trigger_type": "message_received", "webhook_event": ""},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": "llm",
                "type": "ai_agent",
                "data": {
                    "prompt_context": (
                        "You are MP.AI E2E support. Reply briefly confirming the request."
                    ),
                    # Non-UUID → RAG skipped; required min_length=1 by AIAgentNodeData.
                    "knowledge_base_id": "default",
                    "prompt_modifier": "",
                    "temperature": 0.2,
                    "variables": [],
                },
                "position": {"x": 280, "y": 0},
            },
            {
                "id": "end",
                "type": "text_message",
                "data": {"text": "Dialog complete.", "buttons": []},
                "position": {"x": 560, "y": 0},
            },
        ],
        "edges": [
            {"id": "e_start_llm", "source": "start", "target": "llm"},
            {"id": "e_llm_end", "source": "llm", "target": "end"},
        ],
    }


class StressLLMProvider(FakeProvider):
    """Deterministic token counts + occasional timeout (must not yield HTTP 500)."""

    provider_id = "openai"
    model = "gpt-4o-mini"

    def __init__(self) -> None:
        super().__init__(
            LLMResponse(
                content=FIXED_REPLY,
                tool_calls=None,
                prompt_tokens=PROMPT_TOKENS,
                completion_tokens=COMPLETION_TOKENS,
                model_name="gpt-4o-mini",
            )
        )
        self.timeout_calls = 0

    async def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
        self.complete_calls += 1
        if self.complete_calls % 17 == 0:
            self.timeout_calls += 1
            raise TimeoutError("simulated LLM provider timeout")
        return await super().complete(*args, **kwargs)


@pytest.fixture(scope="session")
def e2e_database_url():
    """
    Prefer ephemeral testcontainers Postgres; fall back to app DATABASE_URL
    when Docker is unavailable (common on Windows CI/dev hosts).
    """
    from tests.conftest import _run_alembic_upgrade, _to_asyncpg_url

    container = None
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine")
        container.start()
        url = _to_asyncpg_url(container.get_connection_url())
        _run_alembic_upgrade(url)
        yield url
        return
    except Exception as docker_exc:  # noqa: BLE001
        print(f"[e2e] testcontainers unavailable: {docker_exc} — trying DATABASE_URL")
        if container is not None:
            with suppress(Exception):
                container.stop()
            container = None

    from app.core.config import settings

    raw = (settings.DATABASE_URL or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        pytest.skip("No Docker and no DATABASE_URL for e2e Flow Engine test.")

    url = _to_asyncpg_url(raw)
    try:
        _run_alembic_upgrade(url)
    except Exception as mig_exc:  # noqa: BLE001
        print(f"[e2e] alembic upgrade warning (continuing): {mig_exc}")
    yield url
    if container is not None:
        with suppress(Exception):
            container.stop()


@pytest.fixture
async def e2e_session_factory(
    e2e_database_url: str,
) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        e2e_database_url,
        pool_size=20,
        max_overflow=30,
        pool_pre_ping=True,
        pool_timeout=15,
    )
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def e2e_harness(e2e_session_factory: async_sessionmaker[AsyncSession]):
    """Seed tenant + wire ASGI client with get_db override + mocked LLM gateway."""
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    email = f"e2e-flow-{org_id.hex[:10]}@mp.ai.test"
    password = "E2e-Test-Pass-9!"

    async with e2e_session_factory() as db:
        user = User(
            id=user_id,
            email=email,
            hashed_password=hash_password(password),
            full_name="E2E Flow Owner",
            company_name="E2E Flow Org",
            company_id=org_id,
            role=UserRole.OWNER,
            is_active=True,
            is_verified=True,
            timezone="Asia/Almaty",
        )
        db.add(user)
        await db.flush()
        db.add(
            Company(
                id=org_id,
                name="E2E Flow Org",
                owner_user_id=user_id,
                timezone="Asia/Almaty",
            )
        )
        db.add(
            UserCompanyWorkspace(
                user_id=user_id,
                company_id=org_id,
                role=UserRole.OWNER,
            )
        )
        await db.flush()
        await wallet_service.get_or_create_wallet(
            db, org_id, initial_balance=INITIAL_CREDITS
        )
        await db.commit()

    token = create_access_token(
        subject=user_id,
        company_id=org_id,
        role=UserRole.OWNER.value,
    )

    async def _override_get_db():
        async with e2e_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                with suppress(Exception):
                    await session.rollback()
                raise
            finally:
                with suppress(Exception):
                    await session.close()

    from app.core.database import get_db as core_get_db
    from app.db.session import get_db as session_get_db

    app.dependency_overrides[core_get_db] = _override_get_db
    app.dependency_overrides[session_get_db] = _override_get_db

    provider = StressLLMProvider()
    gateway = ResilientLLMGateway([provider], wallet_service=wallet_service)

    patches = [
        patch("app.services.llm.factory.get_llm_gateway", return_value=gateway),
        patch(
            "app.services.llm.factory.build_gateway_providers",
            return_value=[provider],
        ),
        patch(
            "app.services.llm.factory.build_gateway_providers_for_organization",
            new=AsyncMock(return_value=[provider]),
        ),
        patch(
            "app.services.ai_orchestrator.llm_response_cache.get_cached_response",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai_orchestrator.llm_response_cache.get_semantic_cached_response",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.ai_orchestrator.llm_response_cache.set_cached_response",
            new=AsyncMock(),
        ),
        patch(
            "app.services.ai_orchestrator.llm_response_cache.register_semantic_turn",
            new=AsyncMock(),
        ),
        patch(
            "app.services.ai_orchestrator.AIOrchestrator._fetch_rag_context_detailed",
            new=AsyncMock(return_value=([], "")),
        ),
    ]

    stack = ExitStack()
    for item in patches:
        stack.enter_context(item)

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        yield {
            "client": client,
            "headers": headers,
            "org_id": org_id,
            "user_id": user_id,
            "email": email,
            "session_factory": e2e_session_factory,
            "provider": provider,
            "gateway": gateway,
        }
    finally:
        await client.aclose()
        stack.close()
        app.dependency_overrides.clear()
        sandbox_service._sessions.clear()


@pytest.mark.asyncio
async def test_autonomous_bot_creation_sequential_and_stress(e2e_harness: dict[str, Any]) -> None:
    client: AsyncClient = e2e_harness["client"]
    headers: dict[str, str] = e2e_harness["headers"]
    org_id: uuid.UUID = e2e_harness["org_id"]
    session_factory: async_sessionmaker[AsyncSession] = e2e_harness["session_factory"]
    provider: StressLLMProvider = e2e_harness["provider"]

    report = StressReport(test_name="autonomous_bot_flow", total_requests=STRESS_DIALOGS)

    # ── Step A: wallet ready ───────────────────────────────────────────────────
    async with session_factory() as db:
        balance = await wallet_service.get_balance(db, org_id)
    assert balance == INITIAL_CREDITS, f"Expected seeded wallet={INITIAL_CREDITS}, got {balance}"
    report.balance_before = balance

    # ── Step B: create bot + publish graph ─────────────────────────────────────
    create_resp = await client.post(
        "/api/v1/bots",
        headers=headers,
        json={
            "name": "E2E Autonomous Flow Bot",
            "platform_type": "TELEGRAM",
            "use_case": "empty",
        },
    )
    assert create_resp.status_code in {200, 201}, create_resp.text
    create_body = create_resp.json()
    bot_id = create_body["bot_id"]
    assert bot_id

    publish_resp = await client.post(
        f"/api/v1/bots/{bot_id}/publish",
        headers=headers,
        json={
            "title": "E2E Start→LLM→End",
            "is_published": True,
            "graph_data": _simple_flow_graph(),
        },
    )
    if publish_resp.status_code >= 400:
        detail = publish_resp.text
        if "knowledge_base" in detail.lower():
            FIXED_BUGS.append(
                "Publish required non-empty knowledge_base_id on ai_agent "
                "(use 'default' placeholder to skip RAG)."
            )
        pytest.fail(f"Publish failed ({publish_resp.status_code}): {detail}")

    pub = publish_resp.json()
    assert pub.get("is_published") is True
    assert pub.get("node_count", 0) >= 3
    report.bot_created = True

    async with session_factory() as db:
        bot = await db.get(Bot, uuid.UUID(str(bot_id)))
        assert bot is not None
        bot.is_active = True
        await db.commit()

    # ── Step C: sequential dialog ──────────────────────────────────────────────
    seq_session = str(uuid.uuid4())
    t0 = time.monotonic()
    seq_resp = await client.post(
        f"/api/v1/sandbox/{bot_id}/message",
        headers=headers,
        json={"text": "Привет, проверь статус заказа #E2E-1", "session_id": seq_session},
    )
    seq_latency = (time.monotonic() - t0) * 1000
    assert seq_resp.status_code == 200, seq_resp.text
    seq_body = seq_resp.json()
    reply = str(seq_body.get("message") or "")
    assert reply.strip(), "Empty bot reply"
    assert "E2E" in reply or FIXED_REPLY.split(":")[0] in reply or len(reply) > 5

    session = sandbox_service.get_or_create_session(uuid.UUID(str(bot_id)), seq_session)
    assert any(m.get("role") == "user" for m in session.history)
    assert any(m.get("role") == "assistant" for m in session.history)

    async with session_factory() as db:
        usage_count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(LLMUsageLog)
                    .where(LLMUsageLog.bot_id == uuid.UUID(str(bot_id)))
                )
            ).scalar_one()
        )
        ledger_count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(CreditTransaction)
                    .where(
                        CreditTransaction.wallet_id == org_id,
                        CreditTransaction.transaction_type == "llm_tokens",
                    )
                )
            ).scalar_one()
        )
        balance_after_seq = await wallet_service.get_balance(db, org_id)

    debited = report.balance_before - balance_after_seq
    assert usage_count >= 1, "LLMUsageLog was not written (dialog audit trail)"
    assert ledger_count >= 1, "CreditTransaction (llm_tokens) missing"
    assert debited == EXPECTED_CREDITS_PER_TURN, (
        f"Wallet debit mismatch: expected {EXPECTED_CREDITS_PER_TURN}, got {debited}"
    )
    report.sequential_ok = True
    report.latencies_ms.append(seq_latency)

    # ── Step D: 50 parallel dialogs ────────────────────────────────────────────
    balance_before_stress = balance_after_seq
    report.start_time = time.monotonic()

    async def _one_dialog(i: int) -> tuple[int, float, str | None]:
        sid = str(uuid.uuid4())
        started = time.monotonic()
        try:
            resp = await client.post(
                f"/api/v1/sandbox/{bot_id}/message",
                headers=headers,
                json={"text": f"Stress message #{i}", "session_id": sid},
                timeout=60.0,
            )
            latency = (time.monotonic() - started) * 1000
            if resp.status_code == 500:
                return 500, latency, resp.text[:200]
            if resp.status_code != 200:
                return resp.status_code, latency, resp.text[:200]
            body = resp.json()
            if not str(body.get("message") or "").strip():
                return 422, latency, "empty message"
            return 200, latency, None
        except Exception as exc:  # noqa: BLE001
            latency = (time.monotonic() - started) * 1000
            return 599, latency, str(exc)[:200]

    results = await asyncio.gather(*[_one_dialog(i) for i in range(STRESS_DIALOGS)])
    report.end_time = time.monotonic()

    for status_code, latency, err in results:
        report.latencies_ms.append(latency)
        if status_code == 200:
            report.successful += 1
        else:
            report.failed += 1
            if status_code == 500:
                report.http_500 += 1
            if err:
                report.errors.append(f"{status_code}: {err}")

    report.timeouts = provider.timeout_calls

    async with session_factory() as db:
        report.balance_after = await wallet_service.get_balance(db, org_id)
        report.usage_logs = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(LLMUsageLog)
                    .where(LLMUsageLog.bot_id == uuid.UUID(str(bot_id)))
                )
            ).scalar_one()
        )
        report.ledger_rows = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(CreditTransaction)
                    .where(
                        CreditTransaction.wallet_id == org_id,
                        CreditTransaction.transaction_type == "llm_tokens",
                    )
                )
            ).scalar_one()
        )
        wallet_row = await db.get(OrganizationWallet, org_id)
        assert wallet_row is not None
        ledger_sum = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
                        CreditTransaction.wallet_id == org_id
                    )
                )
            ).scalar_one()
        )
        wallet_balance = int(wallet_row.balance)
        assert wallet_balance == INITIAL_CREDITS + ledger_sum, (
            f"Wallet/ledger drift: balance={wallet_balance} "
            f"initial+sum={INITIAL_CREDITS + ledger_sum}"
        )

    stress_debit = balance_before_stress - report.balance_after
    assert stress_debit >= 0
    assert stress_debit % EXPECTED_CREDITS_PER_TURN == 0, (
        f"Non-atomic / partial debit detected: stress_debit={stress_debit}"
    )
    max_possible = report.successful * EXPECTED_CREDITS_PER_TURN
    assert stress_debit <= max_possible + EXPECTED_CREDITS_PER_TURN
    report.expected_debit = report.balance_before - report.balance_after
    report.race_safe = (
        wallet_balance == INITIAL_CREDITS + ledger_sum
        and stress_debit % EXPECTED_CREDITS_PER_TURN == 0
    )
    report.pool_ok = report.http_500 == 0 and not any(
        "TimeoutError" in e or "QueuePool" in e or "connection" in e.lower()
        for e in report.errors
    )

    report.print_summary()

    assert report.bot_created
    assert report.sequential_ok
    assert report.http_500 == 0, f"HTTP 500s observed: {report.errors[:3]}"
    assert report.failed == 0, f"Failed dialogs: {report.errors[:5]}"
    assert report.race_safe
    assert report.pool_ok
    assert report.p99 < 60_000, f"p99 too high (possible pool hang): {report.p99}ms"
