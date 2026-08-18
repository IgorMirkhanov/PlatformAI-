"""Checkout sessions + idempotent payment settlement (org wallet credits)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.billing import (
    OrganizationSubscription,
    OrganizationSubscriptionStatus,
    PaymentInvoice,
    PaymentInvoiceStatus,
    PaymentProvider,
)
from app.models.users import User
from app.services.billing.payment_catalog import resolve_catalog_item
from app.services.billing.wallet_service import wallet_service
from app.services.stripe_service import StripeNotConfigured, stripe_service

WALLET_TX_DEPOSIT = "DEPOSIT"
WALLET_TX_SUBSCRIPTION_GRANT = "SUBSCRIPTION_GRANT"


class PaymentBillingService:
    async def create_checkout_session(
        self,
        db: AsyncSession,
        *,
        org_id: uuid.UUID,
        user: User,
        item_type: str,
        plan_or_package_id: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        provider: str = PaymentProvider.STRIPE.value,
    ) -> dict[str, Any]:
        catalog = resolve_catalog_item(item_type, plan_or_package_id)
        amount = Decimal(str(catalog.amount_usd))
        tokens = int(catalog.tokens_allocated)
        idempotency_key = secrets.token_urlsafe(24)

        invoice = PaymentInvoice(
            organization_id=org_id,
            provider=provider,
            amount=amount,
            currency=catalog.currency,
            tokens_allocated=tokens,
            status=PaymentInvoiceStatus.PENDING,
            item_type=item_type,
            package_id=plan_or_package_id,
            idempotency_key=idempotency_key,
        )
        db.add(invoice)
        await db.flush()

        checkout_url: str
        external_id: str | None = None

        if provider == PaymentProvider.STRIPE.value:
            if not stripe_service.enabled():
                raise StripeNotConfigured("Stripe is not configured for checkout.")
            session = await stripe_service.create_checkout_session(
                db,
                user,
                float(amount),
                success_url=success_url,
                cancel_url=cancel_url,
                currency="usd",
                extra_metadata={
                    "invoice_id": str(invoice.id),
                    "item_type": item_type,
                    "package_id": plan_or_package_id,
                    "tokens_allocated": str(tokens),
                },
            )
            checkout_url = str(session["url"])
            external_id = str(session.get("id") or "")
        elif provider == PaymentProvider.MANUAL.value:
            checkout_url = f"/dashboard/billing/success?invoice_id={invoice.id}&simulated=1"
            external_id = f"manual:{invoice.id}"
        else:
            raise ValueError(f"Provider '{provider}' checkout is not implemented yet.")

        invoice.external_id = external_id
        await db.flush()
        await db.commit()

        return {
            "checkout_url": checkout_url,
            "invoice_id": str(invoice.id),
            "idempotency_key": idempotency_key,
            "amount": float(amount),
            "tokens_allocated": tokens,
            "provider": provider,
        }

    async def process_successful_payment(
        self,
        db: AsyncSession,
        *,
        external_payment_id: str,
        provider: str,
        provider_signature_data: dict[str, Any] | None = None,
    ) -> bool:
        """
        Idempotent settlement: invoice SUCCEEDED + wallet credit + optional subscription.
        """
        external_payment_id = (external_payment_id or "").strip()
        if not external_payment_id:
            return False

        provider_norm = (provider or "").strip().lower()

        # Use an explicit transaction boundary. If the request session already
        # has a txn open (middleware), operate inside it and let the caller commit.
        started_here = False
        if not db.in_transaction():
            await db.begin()
            started_here = True

        try:
            invoice = await db.scalar(
                select(PaymentInvoice)
                .where(
                    PaymentInvoice.provider == provider_norm,
                    PaymentInvoice.external_id == external_payment_id,
                )
                .with_for_update()
            )
            if invoice is None:
                invoice = await db.scalar(
                    select(PaymentInvoice)
                    .where(PaymentInvoice.id == self._invoice_uuid_or_none(external_payment_id))
                    .with_for_update()
                )

            if invoice is None:
                logger.warning(
                    "Payment.invoice_not_found | provider={p} external={e}",
                    p=provider_norm,
                    e=external_payment_id,
                )
                if started_here:
                    await db.rollback()
                return False

            if invoice.status == PaymentInvoiceStatus.SUCCEEDED:
                logger.info(
                    "Payment.already_settled | invoice={id} external={e}",
                    id=invoice.id,
                    e=external_payment_id,
                )
                if started_here:
                    await db.commit()
                return True

            if invoice.status in {
                PaymentInvoiceStatus.FAILED,
                PaymentInvoiceStatus.CANCELED,
            }:
                if started_here:
                    await db.rollback()
                return False

            invoice.status = PaymentInvoiceStatus.SUCCEEDED
            await db.flush()

            tx_type = (
                WALLET_TX_SUBSCRIPTION_GRANT
                if invoice.item_type == "subscription"
                else WALLET_TX_DEPOSIT
            )
            ref = f"payment:{provider_norm}:{external_payment_id}"

            credit_result = await wallet_service.credit_credits(
                db,
                invoice.organization_id,
                int(invoice.tokens_allocated),
                tx_type,
                description=f"Payment {provider_norm} {external_payment_id}",
                reference_id=ref,
                invoice_id=invoice.id,
                auto_commit=False,
            )
            if credit_result.idempotent_replay:
                logger.info(
                    "Payment.wallet_credit_idempotent | invoice={id}",
                    id=invoice.id,
                )

            if invoice.item_type == "subscription":
                await self._extend_organization_subscription(
                    db,
                    organization_id=invoice.organization_id,
                    plan_id=invoice.package_id or "pro",
                )

            if started_here:
                await db.commit()
        except Exception:
            if started_here:
                await db.rollback()
            raise

        logger.info(
            "Payment.settled | invoice={id} org={org} tokens={tokens}",
            id=invoice.id,
            org=invoice.organization_id,
            tokens=invoice.tokens_allocated,
        )
        return True

    async def expire_organization_subscription_if_needed(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        *,
        auto_commit: bool = False,
    ) -> OrganizationSubscription | None:
        """
        If org subscription is ACTIVE but ``current_period_end`` is in the past,
        mark it CANCELED and roll plan back to ``free`` (Free-tier limits).
        """
        row = await db.scalar(
            select(OrganizationSubscription)
            .where(OrganizationSubscription.organization_id == organization_id)
            .with_for_update()
        )
        if row is None:
            return None

        now = datetime.now(UTC)
        period_end = row.current_period_end
        if period_end is not None and period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=UTC)

        expired = (
            row.status == OrganizationSubscriptionStatus.ACTIVE
            and period_end is not None
            and period_end < now
        )
        if expired:
            previous_plan = row.plan_id
            row.status = OrganizationSubscriptionStatus.CANCELED
            row.plan_id = "free"
            try:
                from app.models.core_models import Organization

                org = await db.get(Organization, organization_id)
                if org is not None and hasattr(org, "stripe_plan"):
                    org.stripe_plan = "FREE"
            except Exception as exc:
                logger.debug(
                    "Payment.org_stripe_plan_sync_skipped | org={org} error={error}",
                    org=organization_id,
                    error=str(exc),
                )
            await db.flush()
            logger.warning(
                "Payment.subscription_expired | org={org} was_plan={plan} period_end={end}",
                org=organization_id,
                plan=previous_plan,
                end=period_end,
            )
            if auto_commit and db.in_transaction():
                await db.commit()

        return row

    async def get_effective_organization_plan(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> str:
        """
        Resolve live plan id for quota checks.

        Expired ACTIVE rows are rolled back to Free. Missing subscription → free.
        """
        row = await self.expire_organization_subscription_if_needed(db, organization_id)
        if row is None:
            return "free"
        if row.status != OrganizationSubscriptionStatus.ACTIVE:
            return "free"
        plan = (row.plan_id or "free").strip().lower()
        return plan or "free"

    async def _extend_organization_subscription(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        plan_id: str,
    ) -> None:
        now = datetime.now(UTC)
        period_end = now + timedelta(days=30)
        row = await db.scalar(
            select(OrganizationSubscription)
            .where(OrganizationSubscription.organization_id == organization_id)
            .with_for_update()
        )
        if row is None:
            db.add(
                OrganizationSubscription(
                    organization_id=organization_id,
                    plan_id=plan_id,
                    status=OrganizationSubscriptionStatus.ACTIVE,
                    current_period_end=period_end,
                )
            )
        else:
            base = row.current_period_end if row.current_period_end and row.current_period_end > now else now
            row.plan_id = plan_id
            row.status = OrganizationSubscriptionStatus.ACTIVE
            row.current_period_end = base + timedelta(days=30)
        await db.flush()

    @staticmethod
    def _invoice_uuid_or_none(raw: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            return None

    def verify_provider_signature(
        self,
        provider: str,
        *,
        raw_body: bytes,
        headers: dict[str, str],
        provider_signature_data: dict[str, Any] | None = None,
    ) -> bool:
        provider_norm = (provider or "").strip().lower()
        if provider_norm == PaymentProvider.STRIPE.value:
            sig = headers.get("stripe-signature") or headers.get("Stripe-Signature")
            if not sig or not app_settings.STRIPE_WEBHOOK_SECRET:
                return False
            try:
                stripe_service._stripe().Webhook.construct_event(
                    raw_body,
                    sig,
                    app_settings.STRIPE_WEBHOOK_SECRET,
                )
                return True
            except Exception:
                return False
        if provider_norm == PaymentProvider.MANUAL.value:
            secret = (app_settings.PAYMENT_WEBHOOK_DEV_SECRET or "dev-payment-secret").encode()
            token = (headers.get("x-payment-signature") or "").strip()
            digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(digest, token)
        if provider_norm == PaymentProvider.YOOKASSA.value:
            # Placeholder — validate when YooKassa credentials are wired.
            return bool(provider_signature_data)
        return False

    async def parse_stripe_checkout_external_id(
        self,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> tuple[str, str] | None:
        """Return (provider, external_session_id) from a verified Stripe webhook."""
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        if not sig or not app_settings.STRIPE_WEBHOOK_SECRET:
            return None
        event = stripe_service._stripe().Webhook.construct_event(
            raw_body,
            sig,
            app_settings.STRIPE_WEBHOOK_SECRET,
        )
        if str(event.get("type")) != "checkout.session.completed":
            return None
        data = event.get("data", {}).get("object", {}) or {}
        session_id = str(data.get("id") or "")
        if not session_id:
            return None
        return PaymentProvider.STRIPE.value, session_id

    async def link_stripe_session_to_invoice(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        metadata: dict[str, Any],
    ) -> PaymentInvoice | None:
        """Attach Stripe session id to pending invoice created at checkout."""
        invoice_raw = metadata.get("invoice_id")
        if not invoice_raw:
            return None
        try:
            invoice_id = uuid.UUID(str(invoice_raw))
        except ValueError:
            return None
        invoice = await db.get(PaymentInvoice, invoice_id)
        if invoice is None:
            return None
        if not invoice.external_id:
            invoice.external_id = session_id
            await db.flush()
        return invoice


payment_billing_service = PaymentBillingService()
