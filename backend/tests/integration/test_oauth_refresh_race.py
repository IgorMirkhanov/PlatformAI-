"""OAuth refresh race — two parallel workers, one amoCRM HTTP call."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.core_models import Company, UserRole
from app.models.tenant_credentials import CredentialKind, CredentialStatus, TenantCredential
from app.models.users import User
from app.services.crypto_service import encrypt_payload
from app.services.crm_orchestrator import CRMOrchestrator
from app.tasks.oauth_refresh_task import _refresh_expiring_oauth_tokens


async def _seed_expiring_amocrm(
    factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    cred_id = uuid.uuid4()
    ciphertext, iv, tag = encrypt_payload(
        {
            "base_domain": "example.amocrm.ru",
            "refresh_token": "refresh-token-1",
            "client_id": "cid",
            "client_secret": "csecret",
            "access_token": "old-access",
        }
    )
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"oauth-{org_id.hex[:12]}@crm.test",
                hashed_password="!",
                company_name="OAuth Org",
                full_name="OAuth Tester",
                company_id=org_id,
                role=UserRole.OWNER,
                timezone="Asia/Almaty",
            )
        )
        await session.flush()
        session.add(Company(id=org_id, name="OAuth Org", owner_user_id=user_id, timezone="Asia/Almaty"))
        await session.flush()
        session.add(
            TenantCredential(
                id=cred_id,
                organization_id=org_id,
                kind=CredentialKind.CRM_AMOCRM.value,
                label="amocrm",
                encrypted_payload=ciphertext,
                encryption_iv=iv,
                encryption_tag=tag,
                status=CredentialStatus.ACTIVE.value,
                oauth_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            )
        )
        await session.commit()
    return cred_id


@pytest.mark.asyncio
async def test_two_parallel_refresh_tasks_one_amocrm_http_call(
    real_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_expiring_amocrm(real_session_factory)

    http_call = AsyncMock(
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
    )

    async def slow_token_request(self, domain, payload):
        await asyncio.sleep(0.25)
        return await http_call()

    monkeypatch.setattr("app.core.database.async_session_factory", real_session_factory)
    monkeypatch.setattr("app.db.session.async_session_factory", real_session_factory)
    monkeypatch.setattr(CRMOrchestrator, "_amocrm_token_request", slow_token_request)

    results = await asyncio.gather(
        _refresh_expiring_oauth_tokens(),
        _refresh_expiring_oauth_tokens(),
    )
    assert http_call.await_count == 1, results
    assert sum(item.get("refreshed", 0) for item in results) == 1
    assert sum(item.get("skipped", 0) for item in results) >= 1
