"""Shared fixtures for backend integration / pipeline tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

# Ensure JWT minting works before app/security modules are imported.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-pytest-suite")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", "test-credentials-encryption-key-32b!")
os.environ.setdefault("ENCRYPTION_KEY", "test-credentials-encryption-key-32b!")


def _to_asyncpg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url


def _run_alembic_upgrade(database_url: str) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    script = f"""
import os
import sys
from pathlib import Path

backend = Path(r"{backend_dir}")
from alembic.config import Config
from alembic import command

sys.path.insert(0, str(backend))
os.chdir(str(backend))

from app.core.config import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
cfg = Config(str(backend / "alembic.ini"))
command.upgrade(cfg, "head")
"""
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
    )


@pytest.fixture(scope="session")
def real_database_url() -> str:
    """
    Session-scoped ephemeral PostgreSQL URL via testcontainers.

    Skips real-DB tests when Docker is unavailable.
    """
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Docker / testcontainers unavailable: {exc}")

    try:
        url = _to_asyncpg_url(container.get_connection_url())
        _run_alembic_upgrade(url)
        yield url
    finally:
        container.stop()


@pytest.fixture(scope="session")
async def real_session_factory(
    real_database_url: str,
) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        real_database_url,
        pool_size=10,
        max_overflow=5,
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


@pytest.fixture
def admin_user():
    from app.core.security import hash_password
    from app.models.core_models import UserRole
    from app.models.users import User

    admin_id = uuid.uuid4()
    return User(
        id=admin_id,
        email="superadmin@mp.ai.test",
        hashed_password=hash_password("admin-test-password"),
        company_name="MP.AI Support",
        full_name="Platform Superadmin",
        company_id=admin_id,
        role=UserRole.OWNER,
        is_superadmin=True,
        timezone="Asia/Almaty",
    )


@pytest.fixture
def client_user():
    from app.models.core_models import UserRole
    from app.models.users import User

    client_id = uuid.uuid4()
    return User(
        id=client_id,
        email="customer@example.com",
        hashed_password="!",
        company_name="Acme Logistics",
        full_name="Acme Owner",
        company_id=client_id,
        role=UserRole.OWNER,
        is_superadmin=False,
        is_active=True,
        timezone="Asia/Almaty",
    )


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> Any:
        return SimpleNamespace(all=lambda: [self._value] if self._value is not None else [])


class FakeAsyncSession:
    """Minimal async SQLAlchemy session stand-in for admin/impersonation routes."""

    def __init__(self, *, target_user: Any, company: Any) -> None:
        self.target_user = target_user
        self.company = company
        self.added: list[Any] = []
        self.committed = False
        self.flushed = False

    async def execute(self, _stmt: Any) -> _ScalarResult:
        return _ScalarResult(self.target_user)

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self.company

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj: Any) -> None:
        return None


@pytest.fixture
def fake_db_session(client_user):
    company = SimpleNamespace(id=client_user.company_id, name=client_user.company_name)
    return FakeAsyncSession(target_user=client_user, company=company)


@pytest.fixture
def pipeline_graph() -> dict[str, Any]:
    """Trigger → Knowledge Search → CRM Action → LLM compiled graph."""
    return {
        "nodes": [
            {
                "id": "trigger_1",
                "type": "trigger",
                "data": {"trigger_type": "message_received", "webhook_event": ""},
            },
            {
                "id": "ks_1",
                "type": "knowledge_search",
                "data": {
                    "top_k": 3,
                    "query_variable": "message",
                    "output_variable": "rag_context",
                    "knowledge_base_id": "",
                },
            },
            {
                "id": "crm_1",
                "type": "crm_action",
                "data": {
                    "integration_type": "custom_webhook",
                    "action_type": "custom_webhook",
                    "method": "POST",
                    "url": "https://crm.example.com/api/leads",
                    "headers": {
                        "Content-Type": "application/json",
                        "X-Client-Phone": "{{phone}}",
                    },
                    "body_template": (
                        '{"phone": "{{phone}}", "lead_name": "Lead from WhatsApp", '
                        '"context": "{{rag_context}}"}'
                    ),
                    "response_variable": "crm_result",
                    "params": {},
                },
            },
            {
                "id": "llm_1",
                "type": "ai_agent",
                "data": {
                    "prompt_context": (
                        "Use knowledge: {{rag_context}}. "
                        "CRM ok={{crm_result.success}}. Answer the user."
                    ),
                    "knowledge_base_id": "default",
                    "prompt_modifier": "",
                    "temperature": 0.2,
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "trigger_1", "target": "ks_1"},
            {"id": "e2", "source": "ks_1", "target": "crm_1"},
            {"id": "e3", "source": "crm_1", "target": "llm_1"},
        ],
    }
