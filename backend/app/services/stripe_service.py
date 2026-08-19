"""Stripe SDK wrapper — wallet top-up Checkout + Customer Portal.

Works alongside ``stripe_billing_service`` (org subscription plans).
This module owns one-time ``mode=payment`` top-ups credited to ``Subscription.balance``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.core_models import (
    BillingTransaction,
    BillingTransactionType,
    Organization,
)
from app.models.saas_metering import ProcessedStripeEvent, StripeCustomer, StripeCustomerLink
from app.models.users import User
from app.services.pricing_service import USD_TO_KZT
from app.services.wallet_service import wallet_service


class StripeNotConfigured(RuntimeError):
    """Raised when Stripe secret / webhook secrets are missing."""


class StripeService:
    """User-centric Stripe helpers (Checkout top-up + Billing Portal)."""

    def enabled(self) -> bool:
        return bool(self._api_key())

    def _api_key(self) -> str | None:
        # Prefer STRIPE_API_KEY (requested alias), fall back to STRIPE_SECRET_KEY.
        return (settings.STRIPE_API_KEY or settings.STRIPE_SECRET_KEY or "").strip() or None

    def _stripe(self):
        key = self._api_key()
        if not key:
            raise StripeNotConfigured("STRIPE_API_KEY / STRIPE_SECRET_KEY is not configured")
        import stripe

        stripe.api_key = key
        return stripe

    async def get_or_create_customer_id(self, db: AsyncSession, user: User) -> str:
        """
        Ensure a Stripe Customer exists for the user.

        Preference order:
          1. ``user.stripe_customer_id``
          2. Org ``StripeCustomer`` / ``Organization.stripe_customer_id``
          3. Create in Stripe and persist on user + org row
        """
        existing = (getattr(user, "stripe_customer_id", None) or "").strip()
        if existing:
            return existing

        org_id = getattr(user, "company_id", None)
        if org_id is not None:
            org_row = await db.scalar(
                select(StripeCustomer).where(StripeCustomer.organization_id == org_id).limit(1)
            )
            if org_row is not None:
                user.stripe_customer_id = org_row.stripe_customer_id
                await db.flush()
                return org_row.stripe_customer_id
            org = await db.get(Organization, org_id)
            if org is not None and (org.stripe_customer_id or "").strip():
                user.stripe_customer_id = org.stripe_customer_id
                await db.flush()
                return str(org.stripe_customer_id)

        stripe = self._stripe()
        customer = stripe.Customer.create(
            email=user.email,
            name=(user.full_name or user.company_name or user.email)[:256],
            metadata={
                "user_id": str(user.id),
                "organization_id": str(org_id or ""),
            },
        )
        customer_id = str(customer["id"])
        user.stripe_customer_id = customer_id

        if org_id is not None:
            db.add(
                StripeCustomer(
                    organization_id=org_id,
                    stripe_customer_id=customer_id,
                    billing_email=user.email,
                    status="none",
                )
            )
            db.add(
                StripeCustomerLink(
                    user_id=user.id,
                    organization_id=org_id,
                    stripe_customer_id=customer_id,
                )
            )
            org = await db.get(Organization, org_id)
            if org is not None:
                org.stripe_customer_id = customer_id
                if not org.stripe_status:
                    org.stripe_status = "none"

        await db.flush()
        logger.info(
            "Stripe.customer_created | user={user} customer={customer}",
            user=user.id,
            customer=customer_id,
        )
        return customer_id

    async def create_checkout_session(
        self,
        db: AsyncSession,
        user: User,
        amount: float,
        *,
        success_url: str | None = None,
        cancel_url: str | None = None,
        currency: str = "usd",
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a one-time payment Checkout Session.

        ``amount`` is USD (or chosen ``currency`` major units). Wallet credit is
        converted to KZT via ``USD_TO_KZT`` when currency is USD.
        """
        if amount is None or float(amount) <= 0:
            raise ValueError("amount must be a positive number")

        amount = float(amount)
        currency_norm = currency.lower()
        # Stripe expects the smallest currency unit (cents / whole tenge for KZT).
        if currency_norm in {"jpy", "krw", "vnd", "kzt"}:
            unit_amount = int(round(amount))
            if unit_amount < 100:
                raise ValueError("Minimum top-up amount is 100 KZT")
        else:
            unit_amount = int(round(amount * 100))
            if unit_amount < 50:  # Stripe minimum ~$0.50 for USD
                raise ValueError("Minimum top-up amount is 0.50")

        customer_id = await self.get_or_create_customer_id(db, user)
        stripe = self._stripe()

        frontend = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
        success = success_url or f"{frontend}/dashboard/billing?checkout=success"
        cancel = cancel_url or f"{frontend}/dashboard/billing?checkout=cancel"
        if "{CHECKOUT_SESSION_ID}" not in success:
            joiner = "&" if "?" in success else "?"
            success = f"{success}{joiner}session_id={{CHECKOUT_SESSION_ID}}"

        amount_kzt = (
            round(amount * USD_TO_KZT, 2)
            if currency_norm == "usd"
            else round(amount, 2)
        )

        session = stripe.checkout.Session.create(
            mode="payment",
            customer=customer_id,
            client_reference_id=str(user.id),
            success_url=success,
            cancel_url=cancel,
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": currency_norm,
                        "unit_amount": unit_amount,
                        "product_data": {
                            "name": "MP.AI Wallet Top-up",
                            "description": f"Credit {amount_kzt:.2f} KZT to platform wallet",
                        },
                    },
                }
            ],
            metadata={
                "purpose": "wallet_topup",
                "user_id": str(user.id),
                "organization_id": str(getattr(user, "company_id", "") or ""),
                "amount_major": str(amount),
                "amount_kzt": str(amount_kzt),
                "currency": currency_norm,
                **(extra_metadata or {}),
            },
            payment_intent_data={
                "metadata": {
                    "purpose": "wallet_topup",
                    "user_id": str(user.id),
                    "organization_id": str(getattr(user, "company_id", "") or ""),
                    **({k: str(v) for k, v in (extra_metadata or {}).items()}),
                }
            },
        )
        await db.commit()
        return {
            "id": session["id"],
            "url": session["url"],
            "amount": amount,
            "amount_kzt": amount_kzt,
            "currency": currency_norm,
        }

    async def charge_saved_payment_method(
        self,
        db: AsyncSession,
        user: User,
        amount: float,
        *,
        currency: str = "usd",
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Off-session charge against the customer's default saved card."""
        if amount is None or float(amount) <= 0:
            raise ValueError("amount must be a positive number")

        currency_norm = currency.lower()
        amount_f = float(amount)
        if currency_norm in {"jpy", "krw", "vnd", "kzt"}:
            unit_amount = int(round(amount_f))
            if unit_amount < 100:
                raise ValueError("Minimum top-up amount is 100 KZT")
        else:
            unit_amount = int(round(amount_f * 100))
            if unit_amount < 50:
                raise ValueError("Minimum top-up amount is 0.50 USD")

        customer_id = await self.get_or_create_customer_id(db, user)
        stripe = self._stripe()
        payment_methods = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
        if not payment_methods.data:
            raise ValueError(
                "No saved card on file. Complete a Stripe Checkout once or add a card in the Customer Portal."
            )
        payment_method_id = payment_methods.data[0].id

        metadata = {
            "purpose": "wallet_topup",
            "user_id": str(user.id),
            "organization_id": str(getattr(user, "company_id", "") or ""),
            **({k: str(v) for k, v in (extra_metadata or {}).items()}),
        }
        intent = stripe.PaymentIntent.create(
            amount=unit_amount,
            currency=currency_norm,
            customer=customer_id,
            payment_method=payment_method_id,
            off_session=True,
            confirm=True,
            metadata=metadata,
        )
        await db.commit()
        return {
            "id": str(intent["id"]),
            "status": str(intent.get("status") or ""),
            "payment_method": payment_method_id,
        }

    async def create_customer_portal(
        self,
        db: AsyncSession,
        user: User,
        *,
        return_url: str | None = None,
    ) -> dict[str, str]:
        customer_id = await self.get_or_create_customer_id(db, user)
        stripe = self._stripe()
        frontend = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url or f"{frontend}/dashboard/billing",
        )
        await db.commit()
        return {"url": session["url"]}

    async def handle_webhook(
        self,
        db: AsyncSession,
        payload: bytes,
        signature: str,
    ) -> dict[str, Any]:
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise StripeNotConfigured("STRIPE_WEBHOOK_SECRET is not configured")

        stripe = self._stripe()
        event = stripe.Webhook.construct_event(
            payload, signature, settings.STRIPE_WEBHOOK_SECRET
        )
        event_id = str(event["id"])
        event_type = str(event["type"])

        # Idempotency gate — never credit a wallet twice for the same Stripe event.
        seen = await db.scalar(
            select(ProcessedStripeEvent).where(ProcessedStripeEvent.event_id == event_id)
        )
        if seen is not None:
            logger.info(
                "Stripe.webhook_duplicate | type={type} id={id}",
                type=event_type,
                id=event_id,
            )
            return {"status": "ok", "duplicate": True, "event_id": event_id, "type": event_type}

        if event_type == "checkout.session.completed":
            data = event.get("data", {}).get("object", {}) or {}
            metadata = data.get("metadata") or {}
            mode = str(data.get("mode") or "")
            purpose = str(metadata.get("purpose") or "")
            if mode == "payment" or purpose == "wallet_topup":
                await self._credit_wallet_from_checkout(db, event_id=event_id, session=data)
            else:
                from app.services.stripe_billing_service import stripe_billing_service

                await stripe_billing_service._apply_subscription_event(db, event)
        else:
            from app.services.stripe_billing_service import stripe_billing_service

            if event_type == "customer.subscription.updated":
                await stripe_billing_service._apply_subscription_event(db, event)
            elif event_type in {"customer.subscription.deleted", "invoice.payment_failed"}:
                await stripe_billing_service._downgrade_on_cancel(db, event)
            elif event_type == "invoice.paid":
                await stripe_billing_service._apply_invoice_paid(db, event)

        # Record after successful apply. Concurrent workers still safe: unique(event_id)
        # + checkout reference_id idempotency prevent double credits.
        try:
            db.add(ProcessedStripeEvent(event_id=event_id, event_type=event_type))
            await db.flush()
        except IntegrityError:
            logger.info(
                "Stripe.webhook_race_duplicate | type={type} id={id}",
                type=event_type,
                id=event_id,
            )
            await db.commit()
            return {"status": "ok", "duplicate": True, "event_id": event_id, "type": event_type}

        await db.commit()
        logger.info("Stripe.webhook_ok | type={type} id={id}", type=event_type, id=event_id)
        return {"status": "ok", "duplicate": False, "event_id": event_id, "type": event_type}

    async def _credit_wallet_from_checkout(
        self,
        db: AsyncSession,
        *,
        event_id: str,
        session: dict[str, Any],
    ) -> None:
        metadata = session.get("metadata") or {}
        raw_user = session.get("client_reference_id") or metadata.get("user_id")
        if not raw_user:
            logger.warning("Stripe.topup_missing_user | event={id}", id=event_id)
            return
        try:
            user_id = uuid.UUID(str(raw_user))
        except ValueError:
            logger.warning("Stripe.topup_bad_user | event={id} raw={raw}", id=event_id, raw=raw_user)
            return

        user = await db.get(User, user_id)
        if user is None:
            logger.warning("Stripe.topup_user_not_found | user={user}", user=user_id)
            return

        # Prefer metadata amount_kzt; else derive from Stripe amount_total (cents).
        amount_kzt: Decimal
        if metadata.get("amount_kzt"):
            amount_kzt = Decimal(str(metadata["amount_kzt"])).quantize(Decimal("0.01"))
        else:
            total_cents = int(session.get("amount_total") or 0)
            currency = str(session.get("currency") or "usd").lower()
            major = Decimal(total_cents) / Decimal(100)
            if currency == "usd":
                amount_kzt = (major * Decimal(str(USD_TO_KZT))).quantize(Decimal("0.01"))
            else:
                amount_kzt = major.quantize(Decimal("0.01"))

        if amount_kzt <= 0:
            logger.warning("Stripe.topup_zero_amount | event={id}", id=event_id)
            return

        session_id = str(session.get("id") or event_id)
        metadata = session.get("metadata") or {}
        if metadata.get("invoice_id"):
            from app.services.billing_service import process_successful_payment

            await process_successful_payment(
                db,
                external_payment_id=session_id,
                provider="stripe",
            )
            logger.info(
                "Stripe.topup_via_payment_invoice | session={sid} invoice={inv}",
                sid=session_id,
                inv=metadata.get("invoice_id"),
            )
            return

        existing_txn = await db.scalar(
            select(BillingTransaction.id)
            .where(BillingTransaction.reference_id == f"stripe_checkout:{session_id}")
            .limit(1)
        )
        if existing_txn is not None:
            logger.info(
                "Stripe.topup_already_credited | event={id} session={sid}",
                id=event_id,
                sid=session_id,
            )
            return

        org_id = getattr(user, "company_id", None)
        await wallet_service.credit_wallet_balance(
            db,
            user_id=user_id,
            amount_kzt=amount_kzt,
            organization_id=org_id,
            description=f"Stripe Checkout wallet top-up (event {event_id})",
            reference_id=f"stripe_checkout:{session_id}",
            transaction_type=BillingTransactionType.TOP_UP,
        )

        logger.warning(
            "Stripe.wallet_credited | user={user} amount_kzt={amount} session={sid} event={eid}",
            user=user_id,
            amount=str(amount_kzt),
            sid=session_id,
            eid=event_id,
        )


stripe_service = StripeService()
