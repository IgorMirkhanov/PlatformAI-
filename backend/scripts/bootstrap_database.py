"""Bootstrap PostgreSQL schema from SQLAlchemy models (idempotent).

Creates all ORM tables (users, bots, projects, flows, channels, billing, …)
and seeds a default Superadmin + Organization + Default Project when empty.

Usage:
    python scripts/bootstrap_database.py
"""

from __future__ import annotations

import asyncio
import os
import uuid

from loguru import logger
from sqlalchemy import func, inspect, select, text

from app.core.database import Base, async_session_factory, engine
from app.core.security import hash_password

# Ensure every mapped model is registered on Base.metadata before create_all.
import app.models  # noqa: F401
from app.models.core_models import Company, Project, UserCompanyWorkspace, UserRole
from app.models.users import User
from app.services.team_service import team_service

DEFAULT_SUPERADMIN_EMAIL = os.getenv("BOOTSTRAP_SUPERADMIN_EMAIL", "admin@mp.ai")
DEFAULT_SUPERADMIN_PASSWORD = os.getenv("BOOTSTRAP_SUPERADMIN_PASSWORD", "ChangeMeNow!")
DEFAULT_SUPERADMIN_NAME = os.getenv("BOOTSTRAP_SUPERADMIN_NAME", "Platform Superadmin")
DEFAULT_COMPANY_NAME = os.getenv("BOOTSTRAP_COMPANY_NAME", "MP.AI Production Console")


def _create_all(sync_conn) -> None:
    """Create missing tables / enums without dropping existing data.

    Tables are created one-by-one with SAVEPOINTs so a duplicate index
    on one model cannot roll back the entire schema bootstrap.
    """
    from sqlalchemy.exc import ProgrammingError

    for table in Base.metadata.sorted_tables:
        nested = sync_conn.begin_nested()
        try:
            table.create(bind=sync_conn, checkfirst=True)
            nested.commit()
        except ProgrammingError as exc:
            nested.rollback()
            message = str(exc).lower()
            if "already exists" in message:
                logger.warning(
                    "Bootstrap.skip_existing | table={table} detail={detail}",
                    table=table.name,
                    detail=str(exc.orig) if getattr(exc, "orig", None) else str(exc),
                )
                continue
            raise


async def create_schema() -> list[str]:
    logger.info("Bootstrap.create_all | starting Base.metadata.create_all")
    async with engine.begin() as connection:
        await connection.run_sync(_create_all)

    async with engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_conn: sorted(inspect(sync_conn).get_table_names()),
        )

    expected = {
        "users",
        "bots",
        "bot_flows",
        "bot_channels",
        "flows",
        "flow_nodes",
        "flow_edges",
        "clients",
        "chat_messages",
        "subscriptions",
        "billing_transactions",
        "companies",
        "projects",
        "user_company_workspaces",
        "admin_audit_logs",
        "bot_diagnostic_logs",
        "knowledge_base_documents",
        "refresh_tokens",
        "password_reset_tokens",
        "oauth_accounts",
        "integrations",
    }
    missing = sorted(expected - set(table_names))
    if missing:
        logger.warning(
            "Bootstrap.tables_missing_after_create_all | missing={missing}",
            missing=missing,
        )
    else:
        logger.info(
            "Bootstrap.schema_ready | tables={count} sample={sample}",
            count=len(table_names),
            sample=",".join(table_names[:12]),
        )
    return table_names


async def _ensure_default_project(session, company: Company) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.organization_id == company.id,
            Project.slug == "default",
        )
    )
    if project is not None:
        return project
    project = Project(
        organization_id=company.id,
        name="Default",
        slug="default",
        description="Default project",
    )
    session.add(project)
    await session.flush()
    return project


async def seed_superadmin_if_empty() -> User | None:
    """Insert the platform superadmin when no users exist yet."""
    async with async_session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(User))
        if count and int(count) > 0:
            logger.info(
                "Bootstrap.superadmin_skip | reason=users_already_exist count={count}",
                count=count,
            )
            existing_admin = await session.scalar(
                select(User).where(User.is_superadmin.is_(True)).limit(1)
            )
            if existing_admin is None:
                first = await session.scalar(
                    select(User).order_by(User.created_at.asc()).limit(1)
                )
                if first is not None:
                    first.is_superadmin = True
                    await session.commit()
                    logger.warning(
                        "Bootstrap.promoted_first_user_to_superadmin | user_id={user_id} email={email}",
                        user_id=first.id,
                        email=first.email,
                    )
                    return first
            companies = (await session.execute(select(Company))).scalars().all()
            for company in companies:
                if not company.slug:
                    company.slug = f"org-{str(company.id).split('-')[0]}"
                await _ensure_default_project(session, company)
            await session.commit()
            return existing_admin

        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=DEFAULT_SUPERADMIN_EMAIL.strip().lower(),
            hashed_password=hash_password(DEFAULT_SUPERADMIN_PASSWORD),
            company_name=DEFAULT_COMPANY_NAME,
            full_name=DEFAULT_SUPERADMIN_NAME,
            company_id=user_id,
            role=UserRole.OWNER,
            is_superadmin=True,
            is_active=True,
            is_verified=True,
            timezone="Asia/Almaty",
        )
        session.add(user)
        await session.flush()

        company = await team_service._ensure_primary_company(session, user)
        if not company.slug:
            company.slug = "mpai-console"
        membership = await session.scalar(
            select(UserCompanyWorkspace).where(
                UserCompanyWorkspace.user_id == user.id,
                UserCompanyWorkspace.company_id == company.id,
            )
        )
        if membership is None:
            session.add(
                UserCompanyWorkspace(
                    user_id=user.id,
                    company_id=company.id,
                    role=UserRole.OWNER,
                )
            )
        await _ensure_default_project(session, company)

        await session.commit()
        await session.refresh(user)

        logger.info(
            "Bootstrap.superadmin_created | user_id={user_id} email={email} company_id={company_id}",
            user_id=user.id,
            email=user.email,
            company_id=user.company_id,
        )
        logger.warning(
            "Bootstrap.superadmin_credentials | email={email} password_env=BOOTSTRAP_SUPERADMIN_PASSWORD "
            "(default password used if unset — change immediately in production)",
            email=user.email,
        )
        return user


async def verify_connectivity() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    logger.info("Bootstrap.database_reachable | url_host_ok=true")


async def bootstrap() -> None:
    await verify_connectivity()
    tables = await create_schema()
    await seed_superadmin_if_empty()
    logger.info(
        "Database.bootstrap_complete | tables={count}",
        count=len(tables),
    )


async def _main() -> None:
    try:
        await bootstrap()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
