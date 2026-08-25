"""Deal upsert idempotency under parallel inbound messages."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.core_models import Bot, Client, Company, PlatformType, UserRole
from app.models.crm.deal import CrmDeal
from app.models.users import User
from app.repositories.crm.deal_repository import compute_dedup_key, deal_repository
from app.services.crm.adapters import AmoCRMAdapter
from app.services.crm.pipeline_service import pipeline_service
from app.services.crm_orchestrator import crm_orchestrator


def test_compute_dedup_key_stable() -> None:
    org = uuid.UUID("11111111-1111-1111-1111-111111111111")
    a = compute_dedup_key(org, "telegram", "777")
    b = compute_dedup_key(org, "TELEGRAM", "777")
    c = compute_dedup_key(org, "telegram", "778")
    assert a == b
    assert a != c
    assert len(a) == 64


async def _seed_org(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"deal-{org_id.hex[:12]}@crm.test",
                hashed_password="!",
                company_name="Deal Org",
                full_name="Deal Tester",
                company_id=org_id,
                role=UserRole.OWNER,
                timezone="Asia/Almaty",
            )
        )
        await session.flush()
        session.add(Company(id=org_id, name="Deal Org", owner_user_id=user_id, timezone="Asia/Almaty"))
        await session.commit()
    return org_id


async def _seed_bot_client(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    org_id = await _seed_org(factory)
    bot_id = uuid.uuid4()
    client_id = uuid.uuid4()
    async with factory() as session:
        user = (
            await session.execute(select(User).where(User.company_id == org_id))
        ).scalar_one()
        session.add(
            Bot(
                id=bot_id,
                user_id=user.id,
                organization_id=org_id,
                name="Deal Bot",
                platform_type=PlatformType.TELEGRAM,
            )
        )
        await session.flush()
        session.add(
            Client(
                id=client_id,
                bot_id=bot_id,
                external_id="chat-1",
                username="lead",
                first_name="Lead",
            )
        )
        await pipeline_service.create_default_pipeline(session, org_id)
        await session.commit()
    return org_id, bot_id, client_id


@pytest.mark.asyncio
async def test_twenty_parallel_upserts_create_one_deal(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(real_session_factory)
    async with real_session_factory() as session:
        pipeline = await pipeline_service.create_default_pipeline(session, org_id)
        await session.commit()
        stage = next(s for s in pipeline.stages if not s.is_won and not s.is_lost)
        pipeline_id = pipeline.id
        stage_id = stage.id

    key = compute_dedup_key(org_id, "telegram", "chat-1")

    async def once() -> bool:
        async with real_session_factory() as session:
            result = await deal_repository(session, organization_id=org_id).upsert_idempotent(
                organization_id=org_id,
                dedup_key=key,
                title="Lead",
                pipeline_id=pipeline_id,
                stage_id=stage_id,
                source="telegram",
            )
            await session.commit()
            return result.was_inserted

    flags = await asyncio.gather(*[once() for _ in range(20)])
    assert sum(1 for flag in flags if flag) == 1

    async with real_session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(CrmDeal).where(CrmDeal.organization_id == org_id)
        )
    assert int(count or 0) == 1


@pytest.mark.asyncio
async def test_twenty_parallel_handle_new_message_one_deal_one_crm_call(
    real_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id, bot_id, client_id = await _seed_bot_client(real_session_factory)
    create_lead = AsyncMock(return_value={"status": "ok"})

    async def once() -> None:
        async with real_session_factory() as session:
            bot = await session.get(Bot, bot_id)
            client = await session.get(Client, client_id)
            assert bot is not None and client is not None
            await crm_orchestrator.handle_new_message_for_crm(
                session,
                bot=bot,
                client=client,
                message_text="hello",
                channel_type="telegram",
                external_chat_id="chat-1",
            )
            await session.commit()

    with patch.object(AmoCRMAdapter, "create_lead", new=create_lead):
        await asyncio.gather(*[once() for _ in range(20)])

    async with real_session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(CrmDeal).where(CrmDeal.organization_id == org_id)
        )
    assert int(count or 0) == 1
    assert create_lead.await_count == 1
