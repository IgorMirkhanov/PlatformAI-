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
from app.services.pricing_service import USD_TO_KZT
from app.services.stripe_service import StripeNotConfigured, stripe_service
from app.services.tiptop_service import TipTopNotConfigured, tiptop_service

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

            await self._credit_subscription_ledger(
                db,
                invoice=invoice,
                provider=provider_norm,
                external_payment_id=external_payment_id,
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
        if provider_norm == PaymentProvider.TIPTOP.value:
            hmac_header = (
                headers.get("content-hmac")
                or headers.get("Content-HMAC")
                or headers.get("x-content-hmac")
            )
            return tiptop_service.verify_webhook_signature(raw_body, hmac_header)
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

    async def process_topup(
        self,
        db: AsyncSession,
        *,
        org_id: uuid.UUID,
        user: User,
        amount: float,
        currency: str = "KZT",
        provider: str = "stripe",
        use_saved_card: bool = False,
        success_url: str | None = None,
        cancel_url: str | None = None,
        tiptop_token: str | None = None,
    ) -> dict[str, Any]:
        """
        Production wallet top-up via Stripe (USD/KZT) or TipTop Pay (KZT).

        Settlement always completes through provider webhooks — never instant mock credit.
        """
        if amount is None or float(amount) <= 0:
            raise ValueError("amount must be a positive number")

        currency_norm = (currency or "KZT").strip().upper()
        provider_norm = (provider or "stripe").strip().lower()
        amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"))

        if currency_norm == "USD":
            credits = int(round(float(amount_dec) * USD_TO_KZT))
            kzt_amount = Decimal(str(round(float(amount_dec) * USD_TO_KZT, 2)))
            charge_amount = float(amount_dec)
            charge_currency = "usd"
        elif currency_norm == "KZT":
            credits = int(amount_dec)
            kzt_amount = amount_dec
            charge_amount = float(amount_dec)
            charge_currency = "kzt"
        else:
            raise ValueError("currency must be KZT or USD")

        if credits <= 0:
            raise ValueError("Minimum top-up amount is too small")

        idempotency_key = secrets.token_urlsafe(24)
        if provider_norm == "stripe":
            invoice_provider = PaymentProvider.STRIPE.value
        elif provider_norm in {"tiptop", "freedom"}:
            invoice_provider = PaymentProvider.TIPTOP.value
            provider_norm = "tiptop"
        else:
            raise ValueError(f"Unsupported payment provider: {provider}")

        if provider_norm == "tiptop" and currency_norm != "KZT":
            raise ValueError("TipTop Pay accepts KZT payments only")

        invoice = PaymentInvoice(
            organization_id=org_id,
            provider=invoice_provider,
            amount=amount_dec if currency_norm == "USD" else amount_dec,
            currency=currency_norm,
            tokens_allocated=credits,
            status=PaymentInvoiceStatus.PENDING,
            item_type="topup",
            package_id="card_custom",
            idempotency_key=idempotency_key,
        )
        db.add(invoice)
        await db.flush()

        metadata = {
            "invoice_id": str(invoice.id),
            "organization_id": str(org_id),
            "item_type": "topup",
            "package_id": "card_custom",
            "tokens_allocated": str(credits),
            "amount_kzt": str(kzt_amount),
            "currency": currency_norm.lower(),
        }

        if provider_norm == "stripe":
            if not stripe_service.enabled():
                raise StripeNotConfigured("STRIPE_SECRET_KEY is not configured")

            if use_saved_card:
                intent = await stripe_service.charge_saved_payment_method(
                    db,
                    user,
                    charge_amount,
                    currency=charge_currency,
                    extra_metadata=metadata,
                )
                invoice.external_id = str(intent.get("id") or "")
                await db.flush()
                await db.commit()
                return {
                    "status": "processing",
                    "invoice_id": str(invoice.id),
                    "message": "Payment submitted. Balance updates after Stripe confirmation.",
                }

            session = await stripe_service.create_checkout_session(
                db,
                user,
                charge_amount,
                success_url=success_url,
                cancel_url=cancel_url,
                currency=charge_currency,
                extra_metadata=metadata,
            )
            invoice.external_id = str(session.get("id") or "")
            await db.flush()
            await db.commit()
            return {
                "status": "redirect",
                "checkout_url": str(session["url"]),
                "payment_url": str(session["url"]),
                "invoice_id": str(invoice.id),
            }

        if not tiptop_service.enabled():
            raise TipTopNotConfigured("TIPTOP_PUBLIC_ID / TIPTOP_API_SECRET are not configured")

        description = f"MP.AI wallet top-up {kzt_amount} KZT"
        if use_saved_card:
            charge = await tiptop_service.charge_saved_token(
                amount_kzt=kzt_amount,
                token=tiptop_token or "",
                invoice_id=invoice.id,
                organization_id=org_id,
                user_email=user.email,
                description=description,
            )
            invoice.external_id = str(charge.get("transaction_id") or "")
            await db.flush()
            await db.commit()
            return {
                "status": "processing",
                "invoice_id": str(invoice.id),
                "message": "Payment submitted. Balance updates after TipTop confirmation.",
            }

        order = await tiptop_service.create_payment_order(
            amount_kzt=kzt_amount,
            invoice_id=invoice.id,
            organization_id=org_id,
            user_email=user.email,
            description=description,
            success_url=success_url,
            fail_url=cancel_url,
        )
        invoice.external_id = str(order.get("order_id") or "")
        await db.flush()
        await db.commit()
        payment_url = str(order.get("payment_url") or "")
        return {
            "status": "redirect",
            "checkout_url": payment_url,
            "payment_url": payment_url,
            "invoice_id": str(invoice.id),
            "widget_params": {
                "public_id": order.get("public_id"),
                "amount": float(kzt_amount),
                "currency": "KZT",
                "invoice_id": str(invoice.id),
            },
        }

    async def process_card_topup(
        self,
        db: AsyncSession,
        *,
        org_id: uuid.UUID,
        user: User,
        amount_kzt: float,
        success_url: str | None = None,
        cancel_url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Backward-compatible KZT top-up alias."""
        provider = kwargs.get("provider", "stripe")
        return await self.process_topup(
            db,
            org_id=org_id,
            user=user,
            amount=amount_kzt,
            currency="KZT",
            provider=provider,
            use_saved_card=bool(kwargs.get("use_saved_card", False)),
            success_url=success_url,
            cancel_url=cancel_url,
            tiptop_token=kwargs.get("tiptop_token"),
        )

    async def _credit_subscription_ledger(
        self,
        db: AsyncSession,
        *,
        invoice: PaymentInvoice,
        provider: str,
        external_payment_id: str,
    ) -> None:
        """Mirror org wallet credit into legacy KZT subscription balance + CARD_DEPOSIT row."""
        from app.models.users import User
        from app.services.billing_service import billing_service

        if invoice.currency.upper() == "KZT":
            kzt_amount = Decimal(str(invoice.tokens_allocated))
        else:
            kzt_amount = Decimal(str(invoice.tokens_allocated))

        owner = await db.scalar(
            select(User)
            .where(User.company_id == invoice.organization_id)
            .order_by(User.created_at.asc())
            .limit(1)
        )
        if owner is None:
            logger.warning(
                "Payment.subscription_owner_missing | org={org} invoice={inv}",
                org=invoice.organization_id,
                inv=invoice.id,
            )
            return

        await billing_service.credit_card_deposit(
            db,
            user_id=owner.id,
            amount=kzt_amount,
            organization_id=invoice.organization_id,
            description=f"Пополнение картой ({provider}) {external_payment_id}",
        )

    async def handle_tiptop_webhook(
        self,
        db: AsyncSession,
        *,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        hmac_header = (
            headers.get("content-hmac")
            or headers.get("Content-HMAC")
            or headers.get("x-content-hmac")
        )
        if not tiptop_service.verify_webhook_signature(raw_body, hmac_header):
            raise ValueError("Invalid TipTop webhook signature")

        payload = tiptop_service.parse_webhook_payload(raw_body)
        if payload is None:
            raise ValueError("Invalid TipTop webhook payload")

        if not tiptop_service.is_completed_status(payload):
            return {"status": "ignored", "provider": "tiptop"}

        external_id = tiptop_service.extract_external_payment_id(payload)
        invoice_raw = payload.get("InvoiceId") or payload.get("invoice_id")
        if not external_id and invoice_raw:
            external_id = str(invoice_raw)

        if not external_id:
            raise ValueError("TipTop webhook missing payment identifier")

        # Link order/transaction id on the pending invoice when needed.
        if invoice_raw:
            try:
                invoice_id = uuid.UUID(str(invoice_raw))
            except ValueError:
                invoice_id = None
            if invoice_id is not None:
                invoice = await db.get(PaymentInvoice, invoice_id)
                if invoice is not None and not invoice.external_id:
                    invoice.external_id = external_id
                    await db.flush()

        processed = await self.process_successful_payment(
            db,
            external_payment_id=external_id,
            provider=PaymentProvider.TIPTOP.value,
        )
        await db.commit()
        return {"status": "ok", "provider": "tiptop", "processed": processed}

    async def handle_payments_webhook(
        self,
        db: AsyncSession,
        *,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Unified payment webhook for Stripe and TipTop Pay."""
        sig = headers.get("stripe-signature") or headers.get("Stripe-Signature")
        if sig and app_settings.STRIPE_WEBHOOK_SECRET:
            return await self._handle_stripe_payments_webhook(db, raw_body=raw_body, sig=sig)

        hmac_header = (
            headers.get("content-hmac")
            or headers.get("Content-HMAC")
            or headers.get("x-content-hmac")
        )
        if hmac_header and tiptop_service.enabled():
            return await self.handle_tiptop_webhook(
                db,
                raw_body=raw_body,
                headers=headers,
            )

        raise ValueError("Unsupported or unsigned payment webhook")

    async def _handle_stripe_payments_webhook(
        self,
        db: AsyncSession,
        *,
        raw_body: bytes,
        sig: str,
    ) -> dict[str, Any]:
        event = stripe_service._stripe().Webhook.construct_event(
            raw_body,
            sig,
            app_settings.STRIPE_WEBHOOK_SECRET,
        )
        event_type = str(event.get("type") or "")
        data = event.get("data", {}).get("object", {}) or {}

        if event_type == "checkout.session.completed":
            session_id = str(data.get("id") or "")
            metadata = data.get("metadata") or {}
            if session_id and metadata.get("invoice_id"):
                await self.link_stripe_session_to_invoice(
                    db,
                    session_id=session_id,
                    metadata=metadata,
                )
            if session_id:
                processed = await self.process_successful_payment(
                    db,
                    external_payment_id=session_id,
                    provider=PaymentProvider.STRIPE.value,
                )
                await db.commit()
                return {"status": "ok", "event": event_type, "processed": processed}

        if event_type == "payment_intent.succeeded":
            pi_id = str(data.get("id") or "")
            metadata = data.get("metadata") or {}
            invoice_raw = metadata.get("invoice_id")
            if invoice_raw:
                try:
                    invoice_id = uuid.UUID(str(invoice_raw))
                except ValueError:
                    invoice_id = None
                if invoice_id is not None:
                    invoice = await db.get(PaymentInvoice, invoice_id)
                    if invoice is not None and not invoice.external_id:
                        invoice.external_id = pi_id
                        await db.flush()
            external_id = pi_id
            if metadata.get("checkout_session_id"):
                external_id = str(metadata["checkout_session_id"])
            processed = await self.process_successful_payment(
                db,
                external_payment_id=external_id,
                provider=PaymentProvider.STRIPE.value,
            )
            await db.commit()
            return {"status": "ok", "event": event_type, "processed": processed}

        return {"status": "ignored", "event": event_type}


payment_billing_service = PaymentBillingService()
