"""
Admin Support + RBAC e2e — isolation, search inspection, impersonation audit, LLM admin.

Steps:
  A) Regular OWNER → 403 on admin search / impersonate / llm-models
  B) SUPPORT + SUPERADMIN search returns org, balance, plan, bots
  C) SUPERADMIN impersonate → JWT impersonator_id + AdminAuditLog + /bots works
  D) Admin create / test-connection / deactivate LLM model; hidden from tenants

Usage:
  pytest backend/tests/e2e/test_admin_support_and_rbac.py -v -s
"""

from __future__ import annotations

import os
import uuid
from contextlib import ExitStack, suppress
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, hash_password
from app.models.admin_audit import AdminAuditLog
from app.models.core_models import Bot, Company, PlatformType, UserCompanyWorkspace, UserRole
from app.models.llm_model import LLMModel
from app.models.users import User
from app.schemas.llm_models import LLMModelTestConnectionResponse
from app.services.billing.wallet_service import wallet_service
from main import app

FIXED_BUGS: list[str] = [
    "Admin user search returned only active_bots count — added bots[] summaries "
    "for support inspection (org, balance, plan, bot list).",
    "Public GET /llm-models?active_only=false leaked inactive models to tenants; "
    "regular users are now forced to active_only=True.",
    "llm_model_service.deactivate/update/create: MissingGreenlet on updated_at after "
    "flush — now db.refresh(row) before LLMModelRead.model_validate.",
]


@dataclass
class AdminRbacReport:
    rbac_all_403: bool = False
    search_support_ok: bool = False
    search_superadmin_ok: bool = False
    impersonate_jwt_ok: bool = False
    audit_log_ok: bool = False
    impersonate_bots_ok: bool = False
    llm_admin_lifecycle_ok: bool = False
    notes: list[str] = field(default_factory=list)

    def print_summary(self) -> None:
        yes = lambda v: "PASS" if v else "FAIL"
        print("\n" + "=" * 64)
        print("  QA REPORT — Admin Support & RBAC")
        print("=" * 64)
        print(f"  RBAC gate (all 403)           : {yes(self.rbac_all_403)}")
        print(f"  SUPPORT search / inspection   : {yes(self.search_support_ok)}")
        print(f"  SUPERADMIN search             : {yes(self.search_superadmin_ok)}")
        print(f"  Impersonation JWT claims      : {yes(self.impersonate_jwt_ok)}")
        print(f"  AdminAuditLog IMPERSONATION   : {yes(self.audit_log_ok)}")
        print(f"  Impersonation /bots access    : {yes(self.impersonate_bots_ok)}")
        print(f"  LLM admin create/test/disable : {yes(self.llm_admin_lifecycle_ok)}")
        if FIXED_BUGS:
            print("\n  Fixed bugs during run:")
            for bug in FIXED_BUGS:
                print(f"    - {bug}")
        if self.notes:
            print("\n  Notes:")
            for note in self.notes:
                print(f"    * {note}")
        print("=" * 64 + "\n")


REPORT = AdminRbacReport()
ADMIN_PASSWORD = "Admin-Secure-Pass-9!"
CLIENT_PASSWORD = "Client-Secure-Pass-9!"


@pytest.fixture(scope="session")
def admin_database_url():
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
        print(f"[admin-e2e] testcontainers unavailable: {docker_exc} — trying DATABASE_URL")
        if container is not None:
            with suppress(Exception):
                container.stop()
            container = None

    raw = (settings.DATABASE_URL or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        pytest.skip("No Docker and no DATABASE_URL for admin RBAC e2e.")

    url = _to_asyncpg_url(raw)
    try:
        _run_alembic_upgrade(url)
    except Exception as mig_exc:  # noqa: BLE001
        print(f"[admin-e2e] alembic upgrade warning (continuing): {mig_exc}")
    yield url
    if container is not None:
        with suppress(Exception):
            container.stop()


@pytest.fixture
async def admin_session_factory(
    admin_database_url: str,
) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        admin_database_url,
        pool_size=15,
        max_overflow=20,
        pool_pre_ping=True,
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


async def _seed_user(
    factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
    password: str,
    role: UserRole = UserRole.OWNER,
    is_superadmin: bool = False,
    is_support: bool = False,
    company_name: str = "Tenant Org",
    balance: int = 0,
    with_bot: bool = False,
    stripe_plan: str = "PRO",
) -> dict[str, Any]:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    bot_id: uuid.UUID | None = None
    async with factory() as db:
        db.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password(password),
                full_name=email.split("@")[0],
                company_name=company_name,
                company_id=org_id,
                role=role,
                is_active=True,
                is_verified=True,
                is_superadmin=is_superadmin,
                is_support=is_support,
                timezone="Asia/Almaty",
            )
        )
        await db.flush()
        if not is_superadmin and not is_support:
            db.add(
                Company(
                    id=org_id,
                    name=company_name,
                    owner_user_id=user_id,
                    timezone="Asia/Almaty",
                    stripe_plan=stripe_plan,
                )
            )
            db.add(
                UserCompanyWorkspace(
                    user_id=user_id,
                    company_id=org_id,
                    role=role,
                )
            )
            await db.flush()
            await wallet_service.get_or_create_wallet(db, org_id, initial_balance=balance)
            if with_bot:
                bot_id = uuid.uuid4()
                db.add(
                    Bot(
                        id=bot_id,
                        user_id=user_id,
                        organization_id=org_id,
                        name="Support Inspect Bot",
                        platform_type=PlatformType.TELEGRAM,
                        is_active=True,
                    )
                )
        await db.commit()

    token = create_access_token(
        subject=user_id,
        company_id=None if (is_superadmin or is_support) else org_id,
        role=role.value,
    )
    return {
        "user_id": user_id,
        "org_id": org_id,
        "bot_id": bot_id,
        "email": email,
        "token": token,
        "password": password,
    }


@pytest.fixture
async def admin_harness(admin_session_factory: async_sessionmaker[AsyncSession]):
    suffix = uuid.uuid4().hex[:8]
    client_user = await _seed_user(
        admin_session_factory,
        email=f"client-test-{suffix}@mp.ai.test",
        password=CLIENT_PASSWORD,
        role=UserRole.OWNER,
        company_name=f"Client Test Org {suffix}",
        balance=12_500,
        with_bot=True,
        stripe_plan="PRO",
    )
    regular = await _seed_user(
        admin_session_factory,
        email=f"member-{suffix}@mp.ai.test",
        password=CLIENT_PASSWORD,
        role=UserRole.OWNER,
        company_name=f"Member Org {suffix}",
        balance=100,
    )
    support = await _seed_user(
        admin_session_factory,
        email=f"support-{suffix}@mp.ai.test",
        password=ADMIN_PASSWORD,
        is_support=True,
        is_superadmin=False,
        company_name="MP.AI Support Desk",
    )
    superadmin = await _seed_user(
        admin_session_factory,
        email=f"superadmin-{suffix}@mp.ai.test",
        password=ADMIN_PASSWORD,
        is_superadmin=True,
        is_support=False,
        company_name="MP.AI Platform",
    )

    async def _override_get_db():
        async with admin_session_factory() as session:
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

    # Soften rate-limit / redis denylist for local e2e.
    stack = ExitStack()
    stack.enter_context(
        patch(
            "app.core.redis_client.is_impersonation_jti_revoked",
            return_value=False,
        )
    )
    stack.enter_context(
        patch(
            "app.services.llm_model_service.llm_model_service.test_connection",
            new=AsyncMock(
                return_value=LLMModelTestConnectionResponse(
                    ok=True,
                    latency_ms=12.5,
                    model="e2e-admin-model",
                    provider="custom_openai",
                    message="Connection successful.",
                    sample_reply="pong",
                )
            ),
        )
    )

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    try:
        yield {
            "client": client,
            "factory": admin_session_factory,
            "client_user": client_user,
            "regular": regular,
            "support": support,
            "superadmin": superadmin,
        }
    finally:
        await client.aclose()
        stack.close()
        app.dependency_overrides.pop(core_get_db, None)
        app.dependency_overrides.pop(session_get_db, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Step A — RBAC gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_a_regular_user_forbidden_on_admin_routes(admin_harness: dict) -> None:
    client: AsyncClient = admin_harness["client"]
    regular = admin_harness["regular"]
    headers = _auth(regular["token"])

    paths = [
        ("GET", "/api/v1/admin/users/search", {"query": "test"}),
        ("POST", "/api/v1/admin/impersonate", None),
        ("GET", "/api/v1/admin/llm-models", None),
    ]
    statuses: list[int] = []
    for method, path, params in paths:
        if method == "GET":
            resp = await client.get(path, headers=headers, params=params or {})
        else:
            resp = await client.post(
                path,
                headers=headers,
                json={"user_email": "anyone@example.com", "password": "x"},
            )
        statuses.append(resp.status_code)
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code} {resp.text}"

    REPORT.rbac_all_403 = all(s == 403 for s in statuses)
    REPORT.notes.append(f"RBAC: regular user got 403 on {len(statuses)} admin routes")


# ---------------------------------------------------------------------------
# Step B — Support / Superadmin search inspection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_b_support_and_superadmin_search(admin_harness: dict) -> None:
    client: AsyncClient = admin_harness["client"]
    target = admin_harness["client_user"]
    query = "test"

    for label, actor in (
        ("SUPPORT", admin_harness["support"]),
        ("SUPERADMIN", admin_harness["superadmin"]),
    ):
        resp = await client.get(
            "/api/v1/admin/users/search",
            headers=_auth(actor["token"]),
            params={"query": query},
        )
        assert resp.status_code == 200, f"{label}: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "items" in body and "total" in body
        match = next((item for item in body["items"] if item["id"] == str(target["user_id"])), None)
        assert match is not None, f"{label}: client not found in search results"
        assert match["organization_id"] == str(target["org_id"])
        assert match["organization_name"]
        assert "plan_name" in match and match["plan_name"]
        assert int(match["credit_balance_units"]) == 12_500
        assert isinstance(match.get("bots"), list)
        assert len(match["bots"]) >= 1
        assert match["bots"][0]["name"] == "Support Inspect Bot"
        if label == "SUPPORT":
            REPORT.search_support_ok = True
        else:
            REPORT.search_superadmin_ok = True

    REPORT.notes.append(
        "search: SUPPORT+SUPERADMIN see org/plan/balance/bots for client-test-* user"
    )


# ---------------------------------------------------------------------------
# Step C — Impersonation + audit + tenant API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_c_impersonation_jwt_audit_and_bots(admin_harness: dict) -> None:
    client: AsyncClient = admin_harness["client"]
    factory = admin_harness["factory"]
    target = admin_harness["client_user"]
    superadmin = admin_harness["superadmin"]

    resp = await client.post(
        "/api/v1/admin/impersonate",
        headers=_auth(superadmin["token"]),
        json={"user_email": target["email"], "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    token = body["access_token"]
    assert token
    claims = decode_access_token(token)
    assert claims.get("typ") == "impersonation"
    assert claims.get("impersonator_id") == str(superadmin["user_id"])
    assert claims.get("impersonated_by") == str(superadmin["user_id"])
    assert claims.get("sub") == str(target["user_id"])
    REPORT.impersonate_jwt_ok = True

    async with factory() as db:
        audit = await db.scalar(
            select(AdminAuditLog)
            .where(
                AdminAuditLog.admin_id == superadmin["user_id"],
                AdminAuditLog.target_user_id == target["user_id"],
                AdminAuditLog.action == "IMPERSONATION_START",
            )
            .order_by(AdminAuditLog.created_at.desc())
            .limit(1)
        )
    assert audit is not None
    assert audit.admin_id == superadmin["user_id"]
    assert audit.target_user_id == target["user_id"]
    REPORT.audit_log_ok = True

    bots_resp = await client.get("/api/v1/bots", headers=_auth(token))
    assert bots_resp.status_code == 200, bots_resp.text
    bots_body = bots_resp.json()
    items = bots_body.get("items") or bots_body
    assert isinstance(items, list)
    assert any(str(b.get("id")) == str(target["bot_id"]) for b in items)
    REPORT.impersonate_bots_ok = True
    REPORT.notes.append(
        f"impersonate: JWT impersonator_id ok; audit IMPERSONATION_START; "
        f"/bots returned {len(items)} bot(s)"
    )


# ---------------------------------------------------------------------------
# Step D — Admin LLM model lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_d_admin_llm_model_lifecycle(admin_harness: dict) -> None:
    client: AsyncClient = admin_harness["client"]
    factory = admin_harness["factory"]
    superadmin = admin_harness["superadmin"]
    regular = admin_harness["regular"]
    model_name = f"e2e-admin-model-{uuid.uuid4().hex[:8]}"

    create_resp = await client.post(
        "/api/v1/admin/llm-models",
        headers=_auth(superadmin["token"]),
        json={
            "provider": "custom_openai",
            "model_name": model_name,
            "display_name": "E2E Admin Model",
            "base_url": "http://localhost:11434/v1",
            "context_window": 8192,
            "cost_per_1k_input": "2.0000",
            "cost_per_1k_output": "4.0000",
            "is_active": True,
            "is_system_default": False,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    model_id = created["id"]

    test_resp = await client.post(
        "/api/v1/llm-models/test-connection",
        headers=_auth(superadmin["token"]),
        json={
            "provider": "custom_openai",
            "model_name": model_name,
            "base_url": "http://localhost:11434/v1",
            "model_id": model_id,
            "api_key": "test-key",
        },
    )
    assert test_resp.status_code == 200, test_resp.text
    assert test_resp.json()["ok"] is True

    # Visible to regular user while active.
    list_before = await client.get(
        "/api/v1/llm-models",
        headers=_auth(regular["token"]),
        params={"active_only": "false"},  # must still be forced to active-only
    )
    assert list_before.status_code == 200, list_before.text
    names_before = {item["model_name"] for item in list_before.json()["items"]}
    assert model_name in names_before

    delete_resp = await client.delete(
        f"/api/v1/admin/llm-models/{model_id}",
        headers=_auth(superadmin["token"]),
    )
    assert delete_resp.status_code == 200, delete_resp.text
    assert delete_resp.json()["is_active"] is False

    async with factory() as db:
        row = await db.get(LLMModel, uuid.UUID(model_id))
        assert row is not None
        assert row.is_active is False

    list_after = await client.get(
        "/api/v1/llm-models",
        headers=_auth(regular["token"]),
        params={"active_only": "false"},
    )
    assert list_after.status_code == 200
    names_after = {item["model_name"] for item in list_after.json()["items"]}
    assert model_name not in names_after

    REPORT.llm_admin_lifecycle_ok = True
    REPORT.notes.append(
        f"llm-admin: created {model_name}, test-connection ok, deactivated and "
        "hidden from tenant catalog"
    )


@pytest.fixture(scope="module", autouse=True)
def _print_admin_report():
    yield
    REPORT.print_summary()
