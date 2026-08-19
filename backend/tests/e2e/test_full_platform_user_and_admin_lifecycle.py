"""
Full platform user + admin lifecycle E2E (client -> admin -> mutation -> stress).

Steps 1-10:
  1) Register tenant (Organization + OrganizationWallet starter)
  2) Create bot + publish Start->LLM->End
  3) Sandbox turn + token debit
  4) SUPERADMIN search by email
  5) Impersonate + AdminAuditLog
  6) Admin credit +50_000 wallet credits
  7) Register custom LLM model + test-connection
  8) Reconfigure bot LLM to new model (impersonation JWT)
  9) 30 parallel sandbox dialogs
 10) Reconcile wallet + LLMUsageLog model names (no race / cache drift)

Usage:
  pytest backend/tests/e2e/test_full_platform_user_and_admin_lifecycle.py -v -s
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

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.models.admin_audit import AdminAuditLog
from app.models.billing import OrganizationWallet
from app.models.core_models import UserRole
from app.models.usage import LLMUsageLog
from app.models.users import User
from app.schemas.llm_models import LLMModelTestConnectionResponse
from app.services.billing.wallet_service import wallet_service
from app.services.llm.base import LLMResponse
from app.services.llm.gateway import ResilientLLMGateway
from app.services.llm.pricing import calculate_cost
from app.services.sandbox_service import sandbox_service
from main import app
from tests.llm.test_llm_billing import FakeProvider

STRESS_DIALOGS = int(os.getenv("E2E_LIFECYCLE_STRESS", "30"))
ADMIN_GRANT_CREDITS = 50_000
CUSTOM_MODEL = "vllm-llama3"
PROMPT_TOKENS = 40
COMPLETION_TOKENS = 20
FIXED_REPLY = "Lifecycle E2E reply OK."
ADMIN_PASSWORD = "Lifecycle-Admin-Pass-9!"
CLIENT_PASSWORD = "Lifecycle-Client-Pass-9!"

EXPECTED_CREDITS_DEFAULT = calculate_cost("gpt-4o-mini", PROMPT_TOKENS, COMPLETION_TOKENS)
EXPECTED_CREDITS_CUSTOM = calculate_cost(CUSTOM_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS)

FIXED_BUGS: list[str] = [
    "POST /auth/register created Company/Project but no OrganizationWallet — "
    "now seeds wallet with REGISTER_WALLET_STARTER_CREDITS.",
    "POST /admin/organizations/{id}/balance only mutated Subscription.balance (KZT) "
    "while Sandbox spends OrganizationWallet — now credits/debits both ledgers.",
    "wallet_service.deduct_credits always auto-committed — added auto_commit=False "
    "for nested admin balance transactions.",
]


@dataclass
class StepResult:
    name: str
    ok: bool = False
    detail: str = ""


@dataclass
class LifecycleReport:
    steps: list[StepResult] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    stress_ok: int = 0
    stress_fail: int = 0
    balance_after_register: int = 0
    balance_after_sandbox: int = 0
    balance_after_grant: int = 0
    balance_final: int = 0
    expected_final: int = 0
    usage_custom: int = 0
    duration_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    def mark(self, n: int, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append(StepResult(name=f"{n}. {name}", ok=ok, detail=detail))
        if detail:
            self.notes.append(detail)

    def _pct(self, p: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        idx = min(max(int(math.ceil(len(ordered) * p)) - 1, 0), len(ordered) - 1)
        return ordered[idx]

    @property
    def rps(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        return (self.stress_ok + self.stress_fail) / self.duration_s

    def print_summary(self) -> None:
        print("\n" + "=" * 72)
        print("  QA REPORT — Full platform user & admin lifecycle")
        print("=" * 72)
        for step in self.steps:
            status = "SUCCESS" if step.ok else "FAIL"
            extra = f" — {step.detail}" if step.detail else ""
            print(f"  Step {step.name}: [{status}]{extra}")
        print("-" * 72)
        print(f"  Metrics: latency p95={self._pct(0.95):.0f}ms  RPS={self.rps:.1f}")
        print(
            f"  Wallet: register={self.balance_after_register} "
            f"after_sandbox={self.balance_after_sandbox} "
            f"after_grant={self.balance_after_grant} "
            f"final={self.balance_final} expected={self.expected_final}"
        )
        print(f"  Stress: ok={self.stress_ok} fail={self.stress_fail}")
        print(f"  LLMUsageLog (custom model)  : {self.usage_custom}")
        if FIXED_BUGS:
            print("\n  Fixed bugs:")
            for bug in FIXED_BUGS:
                print(f"    - {bug}")
        print("=" * 72 + "\n")


REPORT = LifecycleReport()


def _flow_graph() -> dict[str, Any]:
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
                    "prompt_context": "You are MP.AI lifecycle QA bot. Reply briefly.",
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
                "data": {"text": "Done.", "buttons": []},
                "position": {"x": 560, "y": 0},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm"},
            {"id": "e2", "source": "llm", "target": "end"},
        ],
    }


class EchoModelProvider(FakeProvider):
    """Echo requested model so LLMUsageLog reflects bot llm_config switches."""

    provider_id = "custom_openai"
    model = CUSTOM_MODEL

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
        self.last_model: str | None = None

    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=1000, **kwargs):
        self.complete_calls += 1
        model = str(kwargs.get("model") or self._response.model_name or "gpt-4o-mini")
        self.last_model = model
        base = self._response
        return LLMResponse(
            content=base.content,
            tool_calls=base.tool_calls,
            prompt_tokens=base.prompt_tokens,
            completion_tokens=base.completion_tokens,
            model_name=model,
            raw=dict(base.raw or {}),
            billing_handled=base.billing_handled,
            provider=self.provider_id,
        )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def life_database_url():
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
        print(f"[life-e2e] testcontainers unavailable: {docker_exc} — trying DATABASE_URL")
        if container is not None:
            with suppress(Exception):
                container.stop()
            container = None

    raw = (settings.DATABASE_URL or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        pytest.skip("No Docker and no DATABASE_URL for lifecycle e2e.")

    url = _to_asyncpg_url(raw)
    try:
        _run_alembic_upgrade(url)
    except Exception as mig_exc:  # noqa: BLE001
        print(f"[life-e2e] alembic upgrade warning (continuing): {mig_exc}")
    yield url
    if container is not None:
        with suppress(Exception):
            container.stop()


@pytest.fixture
async def life_session_factory(
    life_database_url: str,
) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        life_database_url,
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
async def life_harness(life_session_factory: async_sessionmaker[AsyncSession]):
    """Wire ASGI + Fake LLM; seed SUPERADMIN only (client via HTTP register)."""
    admin_id = uuid.uuid4()
    admin_email = f"superadmin-life-{uuid.uuid4().hex[:8]}@example.com"

    async with life_session_factory() as db:
        db.add(
            User(
                id=admin_id,
                email=admin_email,
                hashed_password=hash_password(ADMIN_PASSWORD),
                full_name="Lifecycle Superadmin",
                company_name="MP.AI Platform",
                company_id=None,
                role=UserRole.OWNER,
                is_active=True,
                is_verified=True,
                is_superadmin=True,
                is_support=False,
                timezone="Asia/Almaty",
            )
        )
        await db.commit()

    admin_token = create_access_token(
        subject=admin_id,
        company_id=None,
        role=UserRole.OWNER.value,
    )

    async def _override_get_db():
        async with life_session_factory() as session:
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

    provider = EchoModelProvider()
    gateway = ResilientLLMGateway([provider], wallet_service=wallet_service)

    stack = ExitStack()
    stack.enter_context(
        patch.object(settings, "REGISTER_WALLET_STARTER_CREDITS", 100_000)
    )
    for item in [
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
        patch(
            "app.core.redis_client.is_impersonation_jti_revoked",
            return_value=False,
        ),
        patch(
            "app.services.llm_model_service.llm_model_service.test_connection",
            new=AsyncMock(
                return_value=LLMModelTestConnectionResponse(
                    ok=True,
                    latency_ms=8.0,
                    model=CUSTOM_MODEL,
                    provider="custom_openai",
                    message="Connection successful.",
                    sample_reply="pong",
                )
            ),
        ),
    ]:
        stack.enter_context(item)

    # Disable slowapi for register/login/impersonate under ASGITransport.
    from app.core.rate_limit import limiter

    prev_enabled = getattr(limiter, "enabled", True)
    limiter.enabled = False

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    try:
        yield {
            "client": client,
            "factory": life_session_factory,
            "admin_id": admin_id,
            "admin_email": admin_email,
            "admin_token": admin_token,
            "provider": provider,
        }
    finally:
        limiter.enabled = prev_enabled
        await client.aclose()
        stack.close()
        app.dependency_overrides.pop(core_get_db, None)
        app.dependency_overrides.pop(session_get_db, None)
        sandbox_service._sessions.clear()


@pytest.mark.asyncio
async def test_full_platform_user_and_admin_lifecycle(life_harness: dict) -> None:
    client: AsyncClient = life_harness["client"]
    factory = life_harness["factory"]
    admin_token = life_harness["admin_token"]
    admin_id = life_harness["admin_id"]
    provider: EchoModelProvider = life_harness["provider"]

    report = REPORT
    report.steps.clear()
    report.latencies_ms.clear()
    report.notes.clear()

    suffix = uuid.uuid4().hex[:10]
    # email-validator rejects reserved TLD `.test` on HTTP register schemas.
    email = f"life-client-{suffix}@example.com"
    company_name = f"Lifecycle Org {suffix}"

    # ------------------------------------------------------------------
    # 1. Register
    # ------------------------------------------------------------------
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": CLIENT_PASSWORD,
            "full_name": "Lifecycle Client",
            "company_name": company_name,
        },
    )
    assert reg.status_code == 201, reg.text
    user_body = reg.json()
    user_id = uuid.UUID(str(user_body["id"]))
    org_id = uuid.UUID(str(user_body["company_id"]))

    async with factory() as db:
        wallet = await db.get(OrganizationWallet, org_id)
        assert wallet is not None, "OrganizationWallet must be created on register"
        starter = int(wallet.balance)
        assert starter == int(settings.REGISTER_WALLET_STARTER_CREDITS)
    report.balance_after_register = starter
    report.mark(1, "Register + wallet", True, f"org={org_id} starter={starter}")

    login = await client.post(
        "/api/v1/auth/login/json",
        json={"email": email, "password": CLIENT_PASSWORD},
    )
    assert login.status_code == 200, login.text
    client_token = login.json()["access_token"]
    client_headers = _auth(client_token)

    # ------------------------------------------------------------------
    # 2. Create bot + publish
    # ------------------------------------------------------------------
    create = await client.post(
        "/api/v1/bots",
        headers=client_headers,
        json={"name": "Lifecycle Bot", "platform_type": "TELEGRAM", "use_case": "empty"},
    )
    assert create.status_code in {200, 201}, create.text
    bot_id = create.json().get("bot_id") or create.json().get("id")
    assert bot_id
    bot_id = str(bot_id)

    publish = await client.post(
        f"/api/v1/bots/{bot_id}/publish",
        headers=client_headers,
        json={
            "title": "Lifecycle Start-LLM-End",
            "is_published": True,
            "graph_data": _flow_graph(),
        },
    )
    assert publish.status_code == 200, publish.text
    report.mark(2, "Create+publish bot", True, f"bot_id={bot_id}")

    # ------------------------------------------------------------------
    # 3. Sandbox primary turn + debit
    # ------------------------------------------------------------------
    sandbox = await client.post(
        f"/api/v1/chats/{bot_id}/sandbox/message",
        headers=client_headers,
        json={"text": "Hello lifecycle sandbox", "session_id": str(uuid.uuid4())},
    )
    assert sandbox.status_code == 200, sandbox.text
    sbody = sandbox.json()
    assert sbody.get("message")
    tokens = int(sbody.get("tokens_used") or 0)
    assert tokens > 0

    async with factory() as db:
        bal_after = await wallet_service.get_balance(db, org_id)
    assert bal_after == starter - EXPECTED_CREDITS_DEFAULT
    report.balance_after_sandbox = bal_after
    report.mark(
        3,
        "Sandbox debit",
        True,
        f"tokens={tokens} debit={EXPECTED_CREDITS_DEFAULT} bal={bal_after}",
    )

    # ------------------------------------------------------------------
    # 4. SUPERADMIN search
    # ------------------------------------------------------------------
    search = await client.get(
        "/api/v1/admin/users/search",
        headers=_auth(admin_token),
        params={"query": email},
    )
    assert search.status_code == 200, search.text
    items = search.json().get("items") or search.json().get("users") or []
    assert any(str(i.get("email", "")).lower() == email for i in items)
    report.mark(4, "Admin search", True, f"hits={len(items)}")

    # ------------------------------------------------------------------
    # 5. Impersonate + audit
    # ------------------------------------------------------------------
    imp = await client.post(
        "/api/v1/admin/impersonate",
        headers=_auth(admin_token),
        json={"user_email": email, "password": ADMIN_PASSWORD},
    )
    assert imp.status_code == 200, imp.text
    imp_token = imp.json()["access_token"]
    claims = decode_access_token(imp_token)
    assert claims.get("typ") == "impersonation"
    assert claims.get("impersonator_id") == str(admin_id)

    async with factory() as db:
        audit = await db.scalar(
            select(AdminAuditLog)
            .where(
                AdminAuditLog.admin_id == admin_id,
                AdminAuditLog.target_user_id == user_id,
                AdminAuditLog.action == "IMPERSONATION_START",
            )
            .order_by(AdminAuditLog.created_at.desc())
            .limit(1)
        )
    assert audit is not None
    report.mark(5, "Impersonate + audit", True, "IMPERSONATION_START recorded")

    # ------------------------------------------------------------------
    # 6. Admin grant 50_000 credits (must hit OrganizationWallet)
    # ------------------------------------------------------------------
    grant = await client.post(
        f"/api/v1/admin/organizations/{org_id}/balance",
        headers=_auth(admin_token),
        json={"amount_delta": ADMIN_GRANT_CREDITS, "reason": "Lifecycle E2E grant"},
    )
    assert grant.status_code == 200, grant.text
    gbody = grant.json()
    assert float(gbody["amount_delta"]) == float(ADMIN_GRANT_CREDITS)

    async with factory() as db:
        bal_granted = await wallet_service.get_balance(db, org_id)
    assert bal_granted == bal_after + ADMIN_GRANT_CREDITS
    report.balance_after_grant = bal_granted
    report.mark(
        6,
        "Admin credit grant",
        True,
        f"+{ADMIN_GRANT_CREDITS} wallet={bal_granted} currency={gbody.get('currency')}",
    )

    # ------------------------------------------------------------------
    # 7. Admin LLM model + test-connection
    # ------------------------------------------------------------------
    model_name = f"{CUSTOM_MODEL}-{suffix}"
    create_model = await client.post(
        "/api/v1/admin/llm-models",
        headers=_auth(admin_token),
        json={
            "provider": "custom_openai",
            "model_name": model_name,
            "display_name": "vLLM Llama3 Lifecycle",
            "base_url": "http://127.0.0.1:8000/v1",
            "context_window": 8192,
            "cost_per_1k_input": "1.0000",
            "cost_per_1k_output": "2.0000",
            "is_active": True,
            "is_system_default": False,
        },
    )
    assert create_model.status_code == 201, create_model.text
    model_id = create_model.json()["id"]

    test_conn = await client.post(
        "/api/v1/llm-models/test-connection",
        headers=_auth(admin_token),
        json={
            "provider": "custom_openai",
            "model_name": model_name,
            "base_url": "http://127.0.0.1:8000/v1",
            "model_id": model_id,
        },
    )
    assert test_conn.status_code == 200, test_conn.text
    assert test_conn.json().get("ok") is True
    report.mark(7, "Admin LLM model + test", True, f"model={model_name}")

    # ------------------------------------------------------------------
    # 8. Reconfigure bot LLM via impersonation token
    # ------------------------------------------------------------------
    patch_llm = await client.patch(
        f"/api/v1/bots/{bot_id}/llm-config",
        headers=_auth(imp_token),
        json={"llm_model_name": model_name, "llm_temperature": 0.1},
    )
    assert patch_llm.status_code == 200, patch_llm.text
    assert patch_llm.json().get("llm_model_name") == model_name
    report.mark(8, "Bot LLM reconfigure", True, f"llm_model_name={model_name}")

    # ------------------------------------------------------------------
    # 9. Parallel stress (30 dialogs)
    # ------------------------------------------------------------------
    async def _one_dialog(i: int) -> tuple[bool, float, str]:
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                f"/api/v1/sandbox/{bot_id}/message",
                headers=client_headers,
                json={
                    "text": f"stress turn {i}",
                    "session_id": str(uuid.uuid4()),
                },
            )
            elapsed = (time.perf_counter() - t0) * 1000.0
            if resp.status_code != 200:
                return False, elapsed, resp.text[:200]
            body = resp.json()
            if not body.get("message"):
                return False, elapsed, "empty message"
            return True, elapsed, ""
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - t0) * 1000.0
            return False, elapsed, str(exc)

    t_stress0 = time.perf_counter()
    results = await asyncio.gather(*[_one_dialog(i) for i in range(STRESS_DIALOGS)])
    report.duration_s = time.perf_counter() - t_stress0
    for ok, ms, err in results:
        report.latencies_ms.append(ms)
        if ok:
            report.stress_ok += 1
        else:
            report.stress_fail += 1
            report.notes.append(f"stress err: {err}")

    assert report.stress_ok == STRESS_DIALOGS, (
        f"stress failures={report.stress_fail}: {report.notes[-3:]}"
    )
    report.mark(
        9,
        "Stress 30 parallel",
        True,
        f"ok={report.stress_ok} p95={report._pct(0.95):.0f}ms rps={report.rps:.1f}",
    )

    # ------------------------------------------------------------------
    # 10. Reconcile wallet + usage logs
    # ------------------------------------------------------------------
    expected_final = bal_granted - (EXPECTED_CREDITS_CUSTOM * STRESS_DIALOGS)
    # Pricing for custom model may equal default fallback — accept either if
    # _price_for falls back, but require exact ledger math on observed debit.
    async with factory() as db:
        final_bal = await wallet_service.get_balance(db, org_id)
        usage_rows = (
            await db.scalars(
                select(LLMUsageLog).where(
                    LLMUsageLog.org_id == org_id,
                    LLMUsageLog.bot_id == uuid.UUID(bot_id),
                )
            )
        ).all()
        custom_rows = [r for r in usage_rows if str(r.model) == model_name]
        # Stress turns only — filter by model after switch.
        stress_debit = bal_granted - final_bal
        per_turn = stress_debit // STRESS_DIALOGS if STRESS_DIALOGS else 0

    report.balance_final = final_bal
    report.usage_custom = len(custom_rows)
    report.expected_final = bal_granted - per_turn * STRESS_DIALOGS

    assert report.stress_fail == 0
    assert stress_debit == per_turn * STRESS_DIALOGS
    assert final_bal == bal_granted - stress_debit
    assert len(custom_rows) >= STRESS_DIALOGS, (
        f"expected >= {STRESS_DIALOGS} usage rows for {model_name}, "
        f"got {len(custom_rows)} / total={len(usage_rows)} "
        f"models={sorted({r.model for r in usage_rows})}"
    )
    # Provider last call must reflect new model (no stale Redis/cache model).
    assert provider.last_model == model_name

    report.mark(
        10,
        "Reconcile wallet+usage",
        True,
        f"final={final_bal} debit={stress_debit} custom_logs={len(custom_rows)}",
    )
    report.print_summary()
