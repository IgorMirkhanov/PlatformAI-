"""Plan quota enforcement at Organization level (bots, messages/day, tokens/month, CRM)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Bot, Organization, SubscriptionPlanName
from app.models.crm.deal import DealStatus
from app.models.saas_metering import StripeCustomer, UsageEvent, UsageMetricType
from app.repositories.crm.automation_rule_repository import automation_rule_repository
from app.repositories.crm.contact_repository import contact_repository
from app.repositories.crm.deal_repository import deal_repository
from app.core.pg_locks import LOCK_NS_QUOTA, pg_advisory_xact_lock_uuid
from app.services.billing_service import PLAN_AGENT_LIMITS, billing_service

PLAN_MESSAGE_DAY_LIMITS: dict[SubscriptionPlanName, int] = {
    SubscriptionPlanName.FREE: 200,
    SubscriptionPlanName.PRO: 10_000,
    SubscriptionPlanName.ENTERPRISE: 1_000_000,
}

PLAN_TOKEN_MONTH_LIMITS: dict[SubscriptionPlanName, int] = {
    SubscriptionPlanName.FREE: 100_000,
    SubscriptionPlanName.PRO: 5_000_000,
    SubscriptionPlanName.ENTERPRISE: 100_000_000,
}

# Native CRM entity caps (§7.2) — keys match PLAN_LIMITS.crm_* naming in the spec.
PLAN_CRM_CONTACTS_MAX: dict[SubscriptionPlanName, int] = {
    SubscriptionPlanName.FREE: 100,
    SubscriptionPlanName.PRO: 5_000,
    SubscriptionPlanName.ENTERPRISE: 100_000,
}

PLAN_CRM_DEALS_OPEN_MAX: dict[SubscriptionPlanName, int] = {
    SubscriptionPlanName.FREE: 10,
    SubscriptionPlanName.PRO: 500,
    SubscriptionPlanName.ENTERPRISE: 10_000,
}

PLAN_CRM_AUTOMATION_RULES_MAX: dict[SubscriptionPlanName, int] = {
    SubscriptionPlanName.FREE: 1,
    SubscriptionPlanName.PRO: 20,
    SubscriptionPlanName.ENTERPRISE: 100,
}

PLAN_LIMITS: dict[SubscriptionPlanName, dict[str, int]] = {
    plan: {
        "crm_contacts_max": PLAN_CRM_CONTACTS_MAX[plan],
        "crm_deals_open_max": PLAN_CRM_DEALS_OPEN_MAX[plan],
        "crm_automation_rules_max": PLAN_CRM_AUTOMATION_RULES_MAX[plan],
    }
    for plan in SubscriptionPlanName
}


class QuotaExceeded(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class QuotaService:
    async def _acquire_org_lock(self, db: AsyncSession, organization_id: uuid.UUID) -> None:
        await pg_advisory_xact_lock_uuid(db, LOCK_NS_QUOTA, organization_id)

    async def _plan(self, db: AsyncSession, organization_id: uuid.UUID) -> SubscriptionPlanName:
        # Prefer organization SaaS subscription (expires → Free limits).
        try:
            from app.services.billing.payment_billing_service import payment_billing_service

            plan_id = await payment_billing_service.get_effective_organization_plan(
                db, organization_id
            )
            # Only short-circuit when an OrganizationSubscription row exists
            # (get_effective returns "free" both for missing and expired).
            from app.models.billing import OrganizationSubscription

            has_org_sub = await db.scalar(
                select(OrganizationSubscription.id)
                .where(OrganizationSubscription.organization_id == organization_id)
                .limit(1)
            )
            if has_org_sub is not None:
                return self._coerce_plan_name(plan_id)
        except Exception as exc:
            logger.debug(
                "Quota.org_subscription_plan_skipped | org={org} error={error}",
                org=organization_id,
                error=str(exc),
            )

        customer = await db.scalar(
            select(StripeCustomer).where(StripeCustomer.organization_id == organization_id).limit(1)
        )
        if customer and customer.plan_name:
            try:
                return SubscriptionPlanName(str(customer.plan_name).upper())
            except ValueError:
                pass

        org = await db.get(Organization, organization_id)
        if org and getattr(org, "stripe_plan", None):
            try:
                return SubscriptionPlanName(str(org.stripe_plan).upper())
            except ValueError:
                pass

        if org is not None:
            if org.owner_user_id is None:
                return SubscriptionPlanName.FREE
            sub = await billing_service._get_or_create_active_subscription(db, org.owner_user_id)
            return sub.plan_name
        return SubscriptionPlanName.FREE

    @staticmethod
    def _coerce_plan_name(plan_id: str | None) -> SubscriptionPlanName:
        raw = (plan_id or "free").strip().lower()
        mapping = {
            "free": SubscriptionPlanName.FREE,
            "pro": SubscriptionPlanName.PRO,
            "enterprise": SubscriptionPlanName.ENTERPRISE,
        }
        if raw in mapping:
            return mapping[raw]
        try:
            return SubscriptionPlanName(raw.upper())
        except ValueError:
            return SubscriptionPlanName.FREE

    async def get_organization_limits(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> dict[str, int | str]:
        """Snapshot of effective plan + bot/token caps (for billing / QA checks)."""
        plan = await self._plan(db, organization_id)
        return {
            "plan": plan.value,
            "bots_max": int(PLAN_AGENT_LIMITS.get(plan, 1)),
            "messages_day_max": int(PLAN_MESSAGE_DAY_LIMITS.get(plan, 200)),
            "tokens_month_max": int(PLAN_TOKEN_MONTH_LIMITS.get(plan, 100_000)),
            "crm_contacts_max": int(
                PLAN_CRM_CONTACTS_MAX.get(plan, PLAN_CRM_CONTACTS_MAX[SubscriptionPlanName.FREE])
            ),
        }

    async def assert_can_create_bot(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        # Deprecated: user_id accepted for call-site compatibility.
        user_id: uuid.UUID | None = None,
    ) -> None:
        org_id = organization_id
        await self._acquire_org_lock(db, org_id)
        plan = await self._plan(db, org_id)
        limit = PLAN_AGENT_LIMITS.get(plan, 1)
        count = await db.scalar(
            select(func.count())
            .select_from(Bot)
            .where(
                Bot.organization_id == org_id,
                Bot.deleted_at.is_(None),
            )
        )
        if int(count or 0) >= limit:
            logger.warning(
                "Quota.bots_exceeded | org={org} plan={plan} count={count} limit={limit}",
                org=org_id,
                plan=plan.value,
                count=count,
                limit=limit,
            )
            raise QuotaExceeded(
                "bots_limit",
                f"Plan {plan.value} allows {limit} bot(s). Upgrade billing to add more.",
            )

    async def assert_message_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
    ) -> None:
        plan = await self._plan(db, organization_id)
        limit = PLAN_MESSAGE_DAY_LIMITS.get(plan, 200)
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        used = await db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.organization_id == organization_id,
                UsageEvent.metric_type == UsageMetricType.MESSAGE_IN,
                UsageEvent.created_at >= start,
            )
        )
        if int(used or 0) >= limit:
            raise QuotaExceeded(
                "messages_day_limit",
                f"Daily message quota ({limit}) reached for plan {plan.value}.",
            )

    async def assert_token_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        upcoming_tokens: int = 0,
        *,
        user_id: uuid.UUID | None = None,
    ) -> None:
        plan = await self._plan(db, organization_id)
        limit = PLAN_TOKEN_MONTH_LIMITS.get(plan, 100_000)
        start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = await db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.organization_id == organization_id,
                UsageEvent.metric_type == UsageMetricType.LLM_TOKENS,
                UsageEvent.created_at >= start,
            )
        )
        if int(used or 0) + max(0, upcoming_tokens) > limit:
            raise QuotaExceeded(
                "tokens_month_limit",
                f"Monthly token quota ({limit}) reached for plan {plan.value}.",
            )

    async def check_crm_contacts_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> None:
        """Alias for assert — counts ``crm_contacts`` vs ``crm_contacts_max``."""
        await self.assert_crm_contacts_quota(db, organization_id)

    async def assert_crm_contacts_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> None:
        await self._acquire_org_lock(db, organization_id)
        plan = await self._plan(db, organization_id)
        limit = PLAN_CRM_CONTACTS_MAX.get(plan, PLAN_CRM_CONTACTS_MAX[SubscriptionPlanName.FREE])
        count = await contact_repository(db, organization_id=organization_id).count_filtered()
        if count >= limit:
            logger.warning(
                "Quota.crm_contacts_exceeded | org={org} plan={plan} count={count} limit={limit}",
                org=organization_id,
                plan=plan.value,
                count=count,
                limit=limit,
            )
            raise QuotaExceeded(
                "crm_contacts_limit",
                f"Plan {plan.value} allows {limit} CRM contact(s). Upgrade billing to add more.",
            )

    async def check_crm_deals_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> None:
        await self.assert_crm_deals_open_quota(db, organization_id)

    async def assert_crm_deals_open_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> None:
        await self._acquire_org_lock(db, organization_id)
        plan = await self._plan(db, organization_id)
        limit = PLAN_CRM_DEALS_OPEN_MAX.get(
            plan, PLAN_CRM_DEALS_OPEN_MAX[SubscriptionPlanName.FREE]
        )
        count = await deal_repository(db, organization_id=organization_id).count_deals(
            status=DealStatus.OPEN
        )
        if count >= limit:
            logger.warning(
                "Quota.crm_deals_open_exceeded | org={org} plan={plan} count={count} limit={limit}",
                org=organization_id,
                plan=plan.value,
                count=count,
                limit=limit,
            )
            raise QuotaExceeded(
                "crm_deals_open_limit",
                f"Plan {plan.value} allows {limit} open CRM deal(s). Upgrade billing to add more.",
            )

    async def check_crm_automation_rules_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> None:
        await self.assert_crm_automation_rules_quota(db, organization_id)

    async def assert_crm_automation_rules_quota(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> None:
        await self._acquire_org_lock(db, organization_id)
        plan = await self._plan(db, organization_id)
        limit = PLAN_CRM_AUTOMATION_RULES_MAX.get(
            plan, PLAN_CRM_AUTOMATION_RULES_MAX[SubscriptionPlanName.FREE]
        )
        count = await automation_rule_repository(
            db, organization_id=organization_id
        ).count_filtered()
        if count >= limit:
            logger.warning(
                "Quota.crm_automation_rules_exceeded | org={org} plan={plan} "
                "count={count} limit={limit}",
                org=organization_id,
                plan=plan.value,
                count=count,
                limit=limit,
            )
            raise QuotaExceeded(
                "crm_automation_rules_limit",
                f"Plan {plan.value} allows {limit} CRM automation rule(s). "
                "Upgrade billing to add more.",
            )

    def raise_http(self, exc: QuotaExceeded) -> None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": exc.code, "message": exc.detail, "billing_url": "/billing"},
        )


quota_service = QuotaService()
