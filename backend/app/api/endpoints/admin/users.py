"""Admin users / clients + organizations CRM."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.dependencies.admin import (
    ensure_not_impersonated,
    get_current_admin,
    get_current_superadmin_strict,
    platform_role_of,
)
from app.api.deps import get_current_superadmin
from app.api.endpoints.admin.common import ACTION_BALANCE_ADJUST
from app.api.endpoints.admin.pagination import PaginationParams
from app.core.database import get_db
from app.models.core_models import (
    BillingTransaction,
    BillingTransactionStatus,
    BillingTransactionType,
    Bot,
    Company,
    Subscription,
    SubscriptionStatus,
)
from app.models.billing.organization_wallet import OrganizationWallet
from app.models.users import User
from app.schemas.admin import (
    AdminBalanceAdjustRequest,
    AdminBalanceAdjustResponse,
    AdminClientItem,
    AdminClientListResponse,
    AdminOrganizationItem,
    AdminOrganizationListResponse,
    AdminOrganizationSuspendResponse,
    AdminPlatformRoleUpdate,
    AdminPlatformRoleUpdateResponse,
    AdminUserBotSummary,
    AdminUserSearchItem,
    AdminUserSearchResponse,
)
from app.services.audit_service import audit_service
from app.services.billing_service import billing_service
from app.models.usage import LLMUsageLog

router = APIRouter(tags=["admin-users"])


@router.get(
    "/users/search",
    response_model=AdminUserSearchResponse,
    summary="Search platform users for support / impersonation",
)
async def search_admin_users(
    q: str = Query(default="", max_length=255, alias="q"),
    query: str | None = Query(default=None, max_length=255, alias="query"),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=25, ge=1, le=100),
    limit: int | None = Query(default=None, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> AdminUserSearchResponse:
    """
    List platform users for support.

    Empty ``q`` returns every registered (non-deleted) account, paginated —
    the Admin Panel table renders on page load without typing anything.
    Non-empty ``q`` does a case-insensitive ILIKE match on user email /
    full name and on the organization name.
    """
    _ = current_user
    # ``limit`` is the legacy alias for page_size; ``query`` for q.
    if limit is not None:
        page_size = limit
    raw_query = (q or query or "").strip()

    filters = [User.deleted_at.is_(None)]
    if raw_query:
        pattern = f"%{raw_query}%"
        filters.append(
            or_(
                User.email.ilike(pattern),
                User.full_name.ilike(pattern),
                User.company_name.ilike(pattern),
                Company.name.ilike(pattern),
            )
        )

    active_bots_sq = (
        select(
            Bot.organization_id.label("org_id"),
            func.count(Bot.id).label("active_bots"),
        )
        .where(
            Bot.organization_id.is_not(None),
            Bot.is_active.is_(True),
            Bot.deleted_at.is_(None),
        )
        .group_by(Bot.organization_id)
        .subquery()
    )

    last_bot_sq = (
        select(
            Bot.user_id.label("user_id"),
            func.max(Bot.updated_at).label("last_bot_activity_at"),
        )
        .where(Bot.deleted_at.is_(None))
        .group_by(Bot.user_id)
        .subquery()
    )

    sub_plan_sq = (
        select(Subscription.plan_name)
        .where(
            Subscription.user_id == User.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        .order_by(Subscription.updated_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    stmt = (
        select(
            User,
            Company.name.label("organization_name"),
            Company.stripe_plan,
            func.coalesce(OrganizationWallet.balance, 0).label("wallet_units"),
            func.coalesce(active_bots_sq.c.active_bots, 0).label("active_bots"),
            last_bot_sq.c.last_bot_activity_at,
            sub_plan_sq.label("subscription_plan"),
        )
        .outerjoin(Company, Company.id == User.company_id)
        .outerjoin(OrganizationWallet, OrganizationWallet.organization_id == User.company_id)
        .outerjoin(active_bots_sq, active_bots_sq.c.org_id == User.company_id)
        .outerjoin(last_bot_sq, last_bot_sq.c.user_id == User.id)
        .where(*filters)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    total = int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .outerjoin(Company, Company.id == User.company_id)
            .where(*filters)
        )
        or 0
    )

    rows = (await db.execute(stmt)).all()

    org_ids = {row[0].company_id for row in rows if row[0].company_id is not None}
    bots_by_org: dict[uuid.UUID, list[AdminUserBotSummary]] = {oid: [] for oid in org_ids}
    if org_ids:
        bot_rows = (
            await db.execute(
                select(Bot.id, Bot.name, Bot.is_active, Bot.organization_id).where(
                    Bot.organization_id.in_(org_ids),
                    Bot.deleted_at.is_(None),
                )
            )
        ).all()
        for bot_id, bot_name, bot_active, org_id in bot_rows:
            bots_by_org.setdefault(org_id, []).append(
                AdminUserBotSummary(
                    id=bot_id,
                    name=str(bot_name or ""),
                    is_active=bool(bot_active),
                )
            )

    items: list[AdminUserSearchItem] = []
    for row in rows:
        user: User = row[0]
        wallet_units = int(row.wallet_units or 0)
        plan = row.subscription_plan or row.stripe_plan or "FREE"
        plan_name = plan.value if hasattr(plan, "value") else str(plan)
        last_activity = row.last_bot_activity_at or user.updated_at
        items.append(
            AdminUserSearchItem(
                id=user.id,
                email=user.email,
                full_name=user.full_name or "",
                organization_id=user.company_id,
                organization_name=str(row.organization_name or user.company_name),
                plan_name=plan_name,
                credit_balance_units=wallet_units,
                credit_balance=wallet_units / 100.0,
                active_bots=int(row.active_bots or 0),
                bots=bots_by_org.get(user.company_id, []) if user.company_id else [],
                last_activity_at=last_activity,
                is_active=bool(user.is_active),
                is_superadmin=bool(user.is_superadmin),
                is_support=bool(getattr(user, "is_support", False)),
                platform_role=platform_role_of(user).value,
            )
        )

    total_pages = max(1, (total + page_size - 1) // page_size)
    return AdminUserSearchResponse(
        items=items,
        total=total,
        query=raw_query,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/organizations",
    response_model=AdminOrganizationListResponse,
    summary="List all organizations for the custom Admin CRM panel",
)
async def list_admin_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
) -> AdminOrganizationListResponse:
    _ = current_user
    Owner = aliased(User)

    active_bots_sq = (
        select(
            Bot.organization_id.label("org_id"),
            func.count(Bot.id).label("active_bots"),
        )
        .where(
            Bot.organization_id.is_not(None),
            Bot.is_active.is_(True),
            Bot.deleted_at.is_(None),
        )
        .group_by(Bot.organization_id)
        .subquery()
    )

    llm_spent_sq = (
        select(
            LLMUsageLog.org_id.label("org_id"),
            func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0).label("total_llm_spent"),
        )
        .group_by(LLMUsageLog.org_id)
        .subquery()
    )

    wallet_balance_sq = (
        select(Subscription.balance)
        .where(
            Subscription.user_id == Company.owner_user_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        .order_by(Subscription.updated_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    stmt = (
        select(
            Company.id,
            Company.name,
            Company.slug,
            Company.owner_user_id,
            Company.stripe_status,
            Company.stripe_plan,
            Company.is_suspended,
            Company.created_at,
            Owner.email.label("owner_email"),
            func.coalesce(wallet_balance_sq, 0).label("wallet_balance"),
            func.coalesce(active_bots_sq.c.active_bots, 0).label("active_bots"),
            func.coalesce(llm_spent_sq.c.total_llm_spent, 0.0).label("total_llm_spent"),
        )
        .outerjoin(Owner, Owner.id == Company.owner_user_id)
        .outerjoin(active_bots_sq, active_bots_sq.c.org_id == Company.id)
        .outerjoin(llm_spent_sq, llm_spent_sq.c.org_id == Company.id)
        .where(Company.deleted_at.is_(None))
        .order_by(Company.created_at.desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    organizations = [
        AdminOrganizationItem(
            id=row.id,
            name=row.name,
            slug=row.slug,
            owner_user_id=row.owner_user_id,
            owner_email=str(row.owner_email or ""),
            wallet_balance=float(row.wallet_balance or 0),
            currency="KZT",
            stripe_status=(row.stripe_status or "none"),
            stripe_plan=row.stripe_plan,
            active_bots=int(row.active_bots or 0),
            is_suspended=bool(row.is_suspended),
            total_llm_spent=float(row.total_llm_spent or 0),
            created_at=row.created_at,
        )
        for row in rows
    ]
    return AdminOrganizationListResponse(organizations=organizations, total=len(organizations))


@router.post(
    "/organizations/{org_id}/suspend",
    response_model=AdminOrganizationSuspendResponse,
    summary="Toggle organization suspension kill switch",
)
async def toggle_organization_suspension(
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
    _: User = Depends(ensure_not_impersonated),
) -> AdminOrganizationSuspendResponse:
    company = await db.get(Company, org_id)
    if company is None or company.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    company.is_suspended = not bool(company.is_suspended)
    await audit_service.write(
        db,
        admin_id=current_user.id,
        target_user_id=company.owner_user_id,
        organization_id=company.id,
        action="ORG_SUSPEND" if company.is_suspended else "ORG_UNSUSPEND",
        details={"is_suspended": company.is_suspended},
        ip_address=audit_service.client_ip(request),
    )
    await db.commit()

    logger.warning(
        "Admin.org_suspend_toggle | admin={admin} org={org} suspended={suspended}",
        admin=current_user.id,
        org=company.id,
        suspended=company.is_suspended,
    )
    return AdminOrganizationSuspendResponse(
        organization_id=company.id,
        organization_name=company.name,
        is_suspended=company.is_suspended,
        message=(
            "Organization suspended — LLM execution blocked."
            if company.is_suspended
            else "Organization unsuspended — LLM execution restored."
        ),
    )


@router.post(
    "/organizations/{org_id}/balance",
    response_model=AdminBalanceAdjustResponse,
    summary="Manually adjust an organization wallet balance",
)
async def adjust_organization_balance(
    org_id: uuid.UUID,
    payload: AdminBalanceAdjustRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin),
    _: User = Depends(ensure_not_impersonated),
) -> AdminBalanceAdjustResponse:
    from app.services.billing.wallet_service import (
        InsufficientFundsError,
        wallet_service,
    )

    company = await db.get(Company, org_id)
    if company is None or company.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    subscription = await billing_service._get_or_create_active_subscription(
        db, company.owner_user_id
    )
    previous_sub = Decimal(subscription.balance)
    delta = Decimal(str(payload.amount_delta)).quantize(Decimal("0.01"))
    new_sub = previous_sub + delta
    if new_sub < 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Balance cannot go negative (current={previous_sub}, delta={delta}).",
        )

    subscription.balance = new_sub
    txn_type = (
        BillingTransactionType.MANUAL_DEPOSIT
        if delta > 0
        else BillingTransactionType.SUBSCRIPTION_CHARGE
    )
    txn = BillingTransaction(
        user_id=company.owner_user_id,
        subscription_id=subscription.id,
        organization_id=company.id,
        transaction_type=txn_type,
        amount=abs(delta),
        currency="KZT",
        description=f"Admin balance adjust: {payload.reason}"[:512],
        status=BillingTransactionStatus.SUCCESS,
        reference_id=f"admin_balance:{current_user.id}:{uuid.uuid4().hex[:12]}",
    )
    db.add(txn)
    await db.flush()

    # Primary spendable ledger for Sandbox/LLM is OrganizationWallet (integer credits).
    # amount_delta is interpreted as credit units (same scale as GET /billing/wallet).
    wallet_units = int(delta)
    wallet_ref = f"admin_wallet:{current_user.id}:{uuid.uuid4().hex[:12]}"
    try:
        if wallet_units > 0:
            wallet_result = await wallet_service.credit_credits(
                db,
                company.id,
                wallet_units,
                "admin_adjust",
                description=payload.reason[:512],
                reference_id=wallet_ref,
                auto_commit=False,
            )
        elif wallet_units < 0:
            wallet_result = await wallet_service.deduct_credits(
                db,
                company.id,
                abs(wallet_units),
                "admin_adjust",
                reference_id=wallet_ref,
                auto_commit=False,
            )
        else:
            # Sub-unit delta (e.g. 0.50 KZT) — skip wallet integer change.
            await wallet_service.get_or_create_wallet(db, company.id)
            bal = await wallet_service.get_balance(db, company.id)
            wallet_result = None
            wallet_prev = float(bal)
            wallet_new = float(bal)
    except InsufficientFundsError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if wallet_units != 0 and wallet_result is not None:
        wallet_prev = float(wallet_result.balance_before)
        wallet_new = float(wallet_result.balance_after)

    await audit_service.write(
        db,
        admin_id=current_user.id,
        target_user_id=company.owner_user_id,
        organization_id=company.id,
        action=ACTION_BALANCE_ADJUST,
        details=(
            f"delta={delta} wallet_units={wallet_units} reason={payload.reason}"
        ),
        ip_address=audit_service.client_ip(request),
    )
    await db.commit()

    logger.warning(
        "Admin.balance_adjust | admin={admin} org={org} delta={delta} "
        "sub_balance={sub} wallet={wallet}",
        admin=current_user.id,
        org=company.id,
        delta=str(delta),
        sub=str(new_sub),
        wallet=wallet_new,
    )
    return AdminBalanceAdjustResponse(
        organization_id=company.id,
        organization_name=company.name,
        owner_user_id=company.owner_user_id,
        previous_balance=wallet_prev if wallet_units != 0 else float(previous_sub),
        amount_delta=float(delta),
        new_balance=wallet_new if wallet_units != 0 else float(new_sub),
        currency="CREDITS" if wallet_units != 0 else "KZT",
        transaction_id=txn.id,
        message="Balance updated (subscription + organization wallet).",
    )


async def _list_clients(
    *,
    pagination: PaginationParams,
    db: AsyncSession,
) -> dict:
    from app.api.endpoints.admin.pagination import build_paginated
    from app.schemas.admin import AdminClientItem

    filters: list = [User.deleted_at.is_(None)]
    if pagination.search:
        pattern = f"%{pagination.search}%"
        filters.append(
            or_(
                User.email.ilike(pattern),
                User.full_name.ilike(pattern),
                User.company_name.ilike(pattern),
            )
        )
    if pagination.status:
        status = pagination.status.lower()
        if status in {"active", "true", "1"}:
            filters.append(User.is_active.is_(True))
        elif status in {"inactive", "false", "0"}:
            filters.append(User.is_active.is_(False))
    if pagination.date_from is not None:
        filters.append(User.created_at >= pagination.date_from)
    if pagination.date_to is not None:
        filters.append(User.created_at <= pagination.date_to)

    count_stmt = select(func.count()).select_from(User).where(*filters)
    total = int(await db.scalar(count_stmt) or 0)

    stmt = (
        select(
            User,
            func.coalesce(OrganizationWallet.balance, 0).label("wallet_units"),
        )
        .outerjoin(OrganizationWallet, OrganizationWallet.organization_id == User.company_id)
        .where(*filters)
        .order_by(User.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(stmt)
    rows = list(result.all())

    items = [
        AdminClientItem(
            id=user.id,
            email=user.email,
            full_name=user.full_name or "",
            company_name=user.company_name,
            company_id=user.company_id,
            role=user.role,
            platform_role=(
                "SUPERADMIN"
                if bool(user.is_superadmin)
                else "ADMIN"
                if bool(getattr(user, "is_support", False))
                else "USER"
            ),
            is_superadmin=bool(user.is_superadmin),
            is_support=bool(getattr(user, "is_support", False)),
            is_active=bool(getattr(user, "is_active", True)),
            wallet_balance=float(wallet_units or 0) / 100.0,
            created_at=user.created_at,
        )
        for user, wallet_units in rows
    ]
    payload = build_paginated(
        items,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    payload["clients"] = items
    payload["query"] = pagination.search
    return payload


@router.get(
    "/clients",
    summary="Search platform clients for support impersonation",
)
async def list_admin_clients(
    pagination: PaginationParams = Depends(),
    q: str = Query(default="", max_length=255),
    limit: int | None = Query(default=None, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> dict:
    _ = current_user
    if q.strip() and not pagination.search:
        pagination.search = q.strip()
    if limit is not None and pagination.page == 1 and pagination.page_size == 20:
        pagination.page_size = min(100, limit)
        pagination.offset = (pagination.page - 1) * pagination.page_size
    return await _list_clients(pagination=pagination, db=db)


@router.get(
    "/users",
    summary="List / search platform users (Admin Panel)",
)
async def list_admin_users(
    pagination: PaginationParams = Depends(),
    q: str = Query(default="", max_length=255),
    limit: int | None = Query(default=None, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
) -> dict:
    _ = current_user
    if q.strip() and not pagination.search:
        pagination.search = q.strip()
    if limit is not None and pagination.page == 1 and pagination.page_size == 20:
        pagination.page_size = min(100, limit)
        pagination.offset = (pagination.page - 1) * pagination.page_size
    return await _list_clients(pagination=pagination, db=db)


@router.patch(
    "/users/{target_id}/platform-role",
    response_model=AdminPlatformRoleUpdateResponse,
    summary="Set platform role: USER / ADMIN / SUPERADMIN",
)
async def update_user_platform_role(
    target_id: uuid.UUID,
    payload: AdminPlatformRoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_superadmin_strict),
) -> AdminPlatformRoleUpdateResponse:
    target = await db.get(User, target_id)
    if target is None or getattr(target, "deleted_at", None) is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.")

    new_role = payload.platform_role
    if new_role != "SUPERADMIN" and bool(target.is_superadmin):
        remaining = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.is_superadmin.is_(True),
                User.id != target.id,
                User.deleted_at.is_(None),
            )
        )
        if int(remaining or 0) < 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last Superadmin.",
            )

    previous = (
        "SUPERADMIN"
        if bool(target.is_superadmin)
        else "ADMIN"
        if bool(getattr(target, "is_support", False))
        else "USER"
    )
    if new_role == "SUPERADMIN":
        target.is_superadmin = True
        target.is_support = False
    elif new_role == "ADMIN":
        target.is_superadmin = False
        target.is_support = True
    else:
        target.is_superadmin = False
        target.is_support = False

    await audit_service.write(
        db,
        admin_id=current_user.id,
        target_user_id=target.id,
        organization_id=target.company_id,
        action="PLATFORM_ROLE_UPDATE",
        details=f"from={previous} to={new_role}",
        ip_address=audit_service.client_ip(request),
    )
    await db.commit()
    await db.refresh(target)
    public_role = (
        "SUPERADMIN"
        if bool(target.is_superadmin)
        else "ADMIN"
        if bool(getattr(target, "is_support", False))
        else "USER"
    )
    logger.info(
        "Admin.platform_role_updated | target={email} from={prev} to={role}",
        email=target.email,
        prev=previous,
        role=public_role,
    )
    return AdminPlatformRoleUpdateResponse(
        id=target.id,
        email=target.email,
        platform_role=public_role,
        is_superadmin=bool(target.is_superadmin),
        is_support=bool(getattr(target, "is_support", False)),
    )