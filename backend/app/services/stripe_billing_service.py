"""Stripe Checkout / Portal / webhook — Organization-level customers.

Requires ``stripe`` package and ``STRIPE_*`` settings. Safe no-op when unset.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core_models import (
    BillingTransaction,
    BillingTransactionStatus,
    BillingTransactionType,
    Organization,
    SubscriptionPlanName,
    SubscriptionStatus,
)
from app.models.saas_metering import ProcessedStripeEvent, StripeCustomer, StripeCustomerLink
from app.services.billing_service import PLAN_DURATION_DAYS, PLAN_INITIAL_BALANCE, billing_service


class StripeNotConfigured(RuntimeError):
    pass


class StripeBillingService:
    def enabled(self) -> bool:
        return bool((settings.STRIPE_SECRET_KEY or "").strip())

    def _stripe(self):
        if not self.enabled():
            raise StripeNotConfigured("STRIPE_SECRET_KEY is not configured")
        import stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe

    async def get_org_billing_snapshot(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
    ) -> dict[str, Any]:
        org = await db.get(Organization, organization_id)
        customer = await db.scalar(
            select(StripeCustomer).where(StripeCustomer.organization_id == organization_id).limit(1)
        )
        return {
            "enabled": self.enabled(),
            "organization_id": str(organization_id),
            "stripe_status": (customer.status if customer else None)
            or (getattr(org, "stripe_status", None) if org else None)
            or "none",
            "plan": (customer.plan_name if customer else None)
            or (getattr(org, "stripe_plan", None) if org else None),
            "has_customer": customer is not None,
            "stripe_customer_id": customer.stripe_customer_id if customer else None,
            "stripe_subscription_id": customer.stripe_subscription_id
            if customer
            else (getattr(org, "stripe_subscription_id", None) if org else None),
        }

    async def get_or_create_customer(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        email: str,
        # Backward-compat kwargs (ignored for lookup; still stored on legacy link).
        user_id: uuid.UUID | None = None,
    ) -> str:
        existing = await db.scalar(
            select(StripeCustomer).where(StripeCustomer.organization_id == organization_id).limit(1)
        )
        if existing:
            if email and not existing.billing_email:
                existing.billing_email = email
                await db.flush()
            return existing.stripe_customer_id

        stripe = self._stripe()
        customer = stripe.Customer.create(
            email=email,
            metadata={"organization_id": str(organization_id), "user_id": str(user_id or "")},
        )
        row = StripeCustomer(
            organization_id=organization_id,
            stripe_customer_id=customer["id"],
            billing_email=email,
            status="none",
        )
        db.add(row)
        # Keep legacy link for rollback / dual-read during transition.
        if user_id is not None:
            db.add(
                StripeCustomerLink(
                    user_id=user_id,
                    organization_id=organization_id,
                    stripe_customer_id=customer["id"],
                )
            )
        org = await db.get(Organization, organization_id)
        if org is not None:
            org.stripe_customer_id = customer["id"]
            org.stripe_status = "none"
        await db.flush()
        return customer["id"]

    async def create_checkout_session(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        email: str,
        plan: SubscriptionPlanName | None = None,
        price_id: str | None = None,
        success_url: str,
        cancel_url: str,
        user_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        resolved_plan = plan or SubscriptionPlanName.PRO
        if resolved_plan == SubscriptionPlanName.FREE:
            raise ValueError("FREE plan does not require Checkout")

        resolved_price = price_id or {
            SubscriptionPlanName.PRO: settings.STRIPE_PRICE_PRO,
            SubscriptionPlanName.ENTERPRISE: settings.STRIPE_PRICE_ENTERPRISE,
        }.get(resolved_plan)
        if not resolved_price:
            raise ValueError(f"Stripe price id missing for plan {resolved_plan.value}")

        customer_id = await self.get_or_create_customer(
            db,
            organization_id=organization_id,
            email=email,
            user_id=user_id,
        )
        stripe = self._stripe()
        meta = {
            "organization_id": str(organization_id),
            "plan": resolved_plan.value,
            "user_id": str(user_id or ""),
        }
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": resolved_price, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(organization_id),
            metadata=meta,
            subscription_data={"metadata": meta},
        )
        return {"id": session["id"], "url": session["url"], "organization_id": str(organization_id)}

    async def create_portal_session(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        return_url: str,
    ) -> dict[str, str]:
        link = await db.scalar(
            select(StripeCustomer).where(StripeCustomer.organization_id == organization_id).limit(1)
        )
        if link is None:
            raise ValueError("No Stripe customer for this organization")
        stripe = self._stripe()
        session = stripe.billing_portal.Session.create(
            customer=link.stripe_customer_id,
            return_url=return_url,
        )
        return {"url": session["url"], "organization_id": str(organization_id)}

    async def handle_webhook(self, db: AsyncSession, payload: bytes, signature: str) -> dict[str, Any]:
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise StripeNotConfigured("STRIPE_WEBHOOK_SECRET is not configured")
        stripe = self._stripe()
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
        event_id = event["id"]
        event_type = event["type"]

        seen = await db.scalar(
            select(ProcessedStripeEvent).where(ProcessedStripeEvent.event_id == event_id)
        )
        if seen:
            return {"status": "duplicate", "event_id": event_id}

        db.add(ProcessedStripeEvent(event_id=event_id, event_type=event_type))
        await db.flush()

        if event_type in {"checkout.session.completed", "customer.subscription.updated"}:
            await self._apply_subscription_event(db, event)
        elif event_type in {"customer.subscription.deleted", "invoice.payment_failed"}:
            await self._downgrade_on_cancel(db, event)
        elif event_type == "invoice.paid":
            await self._apply_invoice_paid(db, event)

        await db.commit()
        logger.info("Stripe.webhook_ok | type={type} id={id}", type=event_type, id=event_id)
        return {"status": "ok", "event_id": event_id, "type": event_type}

    async def report_meter_event(
        self,
        *,
        stripe_customer_id: str,
        event_name: str,
        quantity: int,
        timestamp: int | None = None,
    ) -> dict[str, Any] | None:
        if not settings.STRIPE_METERING_ENABLED or not self.enabled():
            return None
        meter_name = (event_name or settings.STRIPE_METER_EVENT_NAME or "").strip()
        if not meter_name or quantity <= 0:
            return None
        try:
            stripe = self._stripe()
            if hasattr(stripe, "billing") and hasattr(stripe.billing, "MeterEvent"):
                event = stripe.billing.MeterEvent.create(
                    event_name=meter_name,
                    payload={"value": str(int(quantity)), "stripe_customer_id": stripe_customer_id},
                    timestamp=timestamp or int(datetime.now(UTC).timestamp()),
                )
                return {"id": getattr(event, "identifier", None) or str(event)}
            logger.debug("Stripe.meter_api_unavailable | event={name}", name=meter_name)
            return None
        except Exception as exc:
            logger.warning(
                "Stripe.meter_failed | customer={cid} error={error}",
                cid=stripe_customer_id,
                error=str(exc),
            )
            return None

    async def report_usage_for_org(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        metric_type: str,
        quantity: int,
    ) -> None:
        if not settings.STRIPE_METERING_ENABLED:
            return
        link = await db.scalar(
            select(StripeCustomer).where(StripeCustomer.organization_id == organization_id).limit(1)
        )
        if link is None:
            return
        event_name = (settings.STRIPE_METER_EVENT_NAME or metric_type.lower()).strip()
        await self.report_meter_event(
            stripe_customer_id=link.stripe_customer_id,
            event_name=event_name,
            quantity=quantity,
        )

    # Backward-compatible alias
    async def report_usage_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        metric_type: str,
        quantity: int,
        organization_id: uuid.UUID | None = None,
    ) -> None:
        org_id = organization_id
        if org_id is None:
            legacy = await db.scalar(
                select(StripeCustomerLink).where(StripeCustomerLink.user_id == user_id).limit(1)
            )
            org_id = legacy.organization_id if legacy else None
        if org_id is None:
            return
        await self.report_usage_for_org(
            db, organization_id=org_id, metric_type=metric_type, quantity=quantity
        )

    async def _sync_org_mirror(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        customer: StripeCustomer,
        plan: SubscriptionPlanName | None,
        status: str,
    ) -> None:
        customer.status = status
        if plan is not None:
            customer.plan_name = plan.value
        org = await db.get(Organization, organization_id)
        if org is not None:
            org.stripe_customer_id = customer.stripe_customer_id
            org.stripe_subscription_id = customer.stripe_subscription_id
            org.stripe_status = status
            if plan is not None:
                org.stripe_plan = plan.value
        await db.flush()

    def _resolve_org_id(self, data: dict[str, Any], metadata: dict[str, Any]) -> uuid.UUID | None:
        raw = (
            metadata.get("organization_id")
            or data.get("client_reference_id")
            or metadata.get("org_id")
        )
        if not raw:
            return None
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            return None

    async def _owner_user_id(self, db: AsyncSession, organization_id: uuid.UUID) -> uuid.UUID | None:
        org = await db.get(Organization, organization_id)
        return org.owner_user_id if org else None

    async def _apply_invoice_paid(self, db: AsyncSession, event: dict[str, Any]) -> None:
        data = event.get("data", {}).get("object", {})
        customer_id = data.get("customer")
        if not customer_id:
            return
        link = await db.scalar(
            select(StripeCustomer).where(StripeCustomer.stripe_customer_id == str(customer_id)).limit(1)
        )
        if link is None:
            return
        await self._sync_org_mirror(
            db,
            organization_id=link.organization_id,
            customer=link,
            plan=SubscriptionPlanName(link.plan_name) if link.plan_name else None,
            status="active",
        )
        owner_id = await self._owner_user_id(db, link.organization_id)
        if owner_id is None:
            return
        sub = await billing_service._get_or_create_active_subscription(db, owner_id)
        sub.status = SubscriptionStatus.ACTIVE
        period_end = data.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")
        if period_end:
            sub.expires_at = datetime.fromtimestamp(int(period_end), tz=UTC)
        else:
            sub.expires_at = datetime.now(UTC) + timedelta(days=30)
        await db.flush()

    async def _apply_subscription_event(self, db: AsyncSession, event: dict[str, Any]) -> None:
        data = event.get("data", {}).get("object", {})
        metadata = data.get("metadata") or {}
        org_id = self._resolve_org_id(data, metadata)
        plan_raw = metadata.get("plan") or SubscriptionPlanName.PRO.value
        user_raw = metadata.get("user_id")

        if org_id is None and user_raw:
            # Legacy webhook without organization_id — map via user link / company.
            try:
                user_id = uuid.UUID(str(user_raw))
            except ValueError:
                logger.warning("Stripe.invalid_user_metadata | event={id}", id=event.get("id"))
                return
            legacy = await db.scalar(
                select(StripeCustomerLink).where(StripeCustomerLink.user_id == user_id).limit(1)
            )
            org_id = legacy.organization_id if legacy else None
            if org_id is None:
                from app.models.users import User

                user = await db.get(User, user_id)
                org_id = getattr(user, "company_id", None) if user else None

        if org_id is None:
            logger.warning("Stripe.missing_org_metadata | event={id}", id=event.get("id"))
            return

        try:
            plan = SubscriptionPlanName(str(plan_raw).upper())
        except ValueError:
            plan = SubscriptionPlanName.PRO

        customer = await db.scalar(
            select(StripeCustomer).where(StripeCustomer.organization_id == org_id).limit(1)
        )
        if customer is None:
            # Create row if Checkout created customer before our insert raced.
            stripe_cus = data.get("customer")
            if not stripe_cus:
                return
            customer = StripeCustomer(
                organization_id=org_id,
                stripe_customer_id=str(stripe_cus),
                status="active",
                plan_name=plan.value,
            )
            db.add(customer)
            await db.flush()

        stripe_sub = data.get("subscription") or data.get("id")
        if isinstance(stripe_sub, str):
            customer.stripe_subscription_id = stripe_sub

        await self._sync_org_mirror(
            db, organization_id=org_id, customer=customer, plan=plan, status="active"
        )

        owner_id = await self._owner_user_id(db, org_id)
        if owner_id is None:
            return
        sub = await billing_service._get_or_create_active_subscription(db, owner_id)
        sub.plan_name = plan
        sub.status = SubscriptionStatus.ACTIVE
        sub.expires_at = datetime.now(UTC) + timedelta(days=PLAN_DURATION_DAYS.get(plan, 30))
        if Decimal(sub.balance) < PLAN_INITIAL_BALANCE.get(plan, Decimal("0")):
            credit = PLAN_INITIAL_BALANCE[plan] - Decimal(sub.balance)
            if credit > 0:
                sub.balance = Decimal(sub.balance) + credit
                db.add(
                    BillingTransaction(
                        user_id=owner_id,
                        subscription_id=sub.id,
                        organization_id=org_id,
                        transaction_type=BillingTransactionType.TOP_UP,
                        status=BillingTransactionStatus.SUCCESS,
                        amount=credit,
                        currency="KZT",
                        description=f"Stripe plan credit {plan.value}",
                        reference_id=str(event.get("id")),
                    )
                )
        await db.flush()

    async def _downgrade_on_cancel(self, db: AsyncSession, event: dict[str, Any]) -> None:
        data = event.get("data", {}).get("object", {})
        metadata = data.get("metadata") or {}
        org_id = self._resolve_org_id(data, metadata)
        if org_id is None:
            customer_id = data.get("customer")
            if customer_id:
                link = await db.scalar(
                    select(StripeCustomer)
                    .where(StripeCustomer.stripe_customer_id == str(customer_id))
                    .limit(1)
                )
                org_id = link.organization_id if link else None
        if org_id is None:
            return

        customer = await db.scalar(
            select(StripeCustomer).where(StripeCustomer.organization_id == org_id).limit(1)
        )
        if customer is not None:
            customer.stripe_subscription_id = None
            await self._sync_org_mirror(
                db,
                organization_id=org_id,
                customer=customer,
                plan=SubscriptionPlanName.FREE,
                status="canceled",
            )

        owner_id = await self._owner_user_id(db, org_id)
        if owner_id is None:
            return
        sub = await billing_service._get_or_create_active_subscription(db, owner_id)
        sub.plan_name = SubscriptionPlanName.FREE
        sub.status = SubscriptionStatus.EXPIRED
        await db.flush()


stripe_billing_service = StripeBillingService()
