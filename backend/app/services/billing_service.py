from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import (
    BillingTransaction,
    BillingTransactionStatus,
    BillingTransactionType,
    Subscription,
    SubscriptionPlanName,
    SubscriptionStatus,
)
from app.models.users import User
from app.schemas.core_schemas import (
    BalanceTopUpRequest,
    BillingStatusResponse,
    BillingTransactionListResponse,
    BillingTransactionRead,
    DepositRequestResponse,
    SubscribeRequest,
    SubscribeResponse,
    SubscriptionCreate,
    SubscriptionRead,
)

PLAN_PRICING: dict[SubscriptionPlanName, Decimal] = {
    SubscriptionPlanName.FREE: Decimal("0.00"),
    SubscriptionPlanName.PRO: Decimal("24500.00"),
    SubscriptionPlanName.ENTERPRISE: Decimal("99000.00"),
}

PLAN_PRICING_USD: dict[SubscriptionPlanName, Decimal] = {
    SubscriptionPlanName.FREE: Decimal("0.00"),
    SubscriptionPlanName.PRO: Decimal("49.00"),
    SubscriptionPlanName.ENTERPRISE: Decimal("199.00"),
}

PLAN_DURATION_DAYS: dict[SubscriptionPlanName, int] = {
    SubscriptionPlanName.FREE: 3650,
    SubscriptionPlanName.PRO: 30,
    SubscriptionPlanName.ENTERPRISE: 30,
}

PLAN_INITIAL_BALANCE: dict[SubscriptionPlanName, Decimal] = {
    SubscriptionPlanName.FREE: Decimal("0.00"),
    SubscriptionPlanName.PRO: Decimal("50000.00"),
    SubscriptionPlanName.ENTERPRISE: Decimal("250000.00"),
}

PLAN_AGENT_LIMITS: dict[SubscriptionPlanName, int] = {
    SubscriptionPlanName.FREE: 1,
    SubscriptionPlanName.PRO: 10,
    SubscriptionPlanName.ENTERPRISE: 999,
}

PLAN_LABELS_RU: dict[SubscriptionPlanName, str] = {
    SubscriptionPlanName.FREE: "FREE",
    SubscriptionPlanName.PRO: "PRO",
    SubscriptionPlanName.ENTERPRISE: "ENTERPRISE",
}

DEFAULT_CURRENCY = "KZT"
BONUS_RATE = Decimal("0.05")
BONUS_THRESHOLD = Decimal("15000.00")


class BillingService:
    """Mock SaaS billing layer for subscriptions and balance management."""

    async def get_billing_status(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | None = None,
    ) -> BillingStatusResponse:
        user = await self._resolve_user(db, user_id)
        subscription = await self._get_or_create_active_subscription(db, user.id)
        subscription = await self._expire_subscription_if_needed(db, subscription)
        bonus_balance = await self._calculate_bonus_balance(db, user.id)

        days_remaining: int | None = None
        if subscription.expires_at is not None:
            delta = subscription.expires_at - datetime.now(UTC)
            days_remaining = max(0, delta.days)

        from app.services.wallet_service import wallet_service

        balance_value = float(subscription.balance or 0)
        return BillingStatusResponse(
            user_id=user.id,
            plan_name=subscription.plan_name,
            balance=balance_value,
            bonus_balance=float(bonus_balance),
            currency=DEFAULT_CURRENCY,
            status=subscription.status,
            expires_at=subscription.expires_at,
            days_remaining=days_remaining,
            active_agents_limit=PLAN_AGENT_LIMITS[subscription.plan_name],
            is_low_balance=wallet_service.is_low_balance(balance_value),
            low_balance_threshold_kzt=float(wallet_service.low_balance_threshold),
        )

    async def list_transactions(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
        transaction_type: BillingTransactionType | None = None,
        type_group: str | None = None,
    ) -> BillingTransactionListResponse:
        user = await self._resolve_user(db, user_id)
        safe_limit = max(1, min(limit, 200))
        safe_offset = max(0, offset)

        filters = [BillingTransaction.user_id == user.id]
        # Hide zero-amount Stripe ack rows if any exist.
        filters.append(BillingTransaction.amount != 0)

        if transaction_type is not None:
            filters.append(BillingTransaction.transaction_type == transaction_type)
        elif type_group:
            group = type_group.strip().lower()
            if group in {"topup", "top_up", "top-up"}:
                filters.append(
                    BillingTransaction.transaction_type.in_(
                        [
                            BillingTransactionType.TOP_UP,
                            BillingTransactionType.MANUAL_DEPOSIT,
                            BillingTransactionType.BONUS,
                            BillingTransactionType.REFUND,
                        ]
                    )
                )
            elif group in {"llm", "deduction", "llm_deduction", "usage"}:
                filters.append(
                    BillingTransaction.transaction_type.in_(
                        [
                            BillingTransactionType.LLM_DEDUCTION,
                            BillingTransactionType.SUBSCRIPTION_CHARGE,
                        ]
                    )
                )

        count_result = await db.execute(
            select(func.count())
            .select_from(BillingTransaction)
            .where(*filters)
        )
        total = int(count_result.scalar_one())

        result = await db.execute(
            select(BillingTransaction)
            .where(*filters)
            .order_by(BillingTransaction.created_at.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
        transactions = result.scalars().all()

        return BillingTransactionListResponse(
            transactions=[BillingTransactionRead.model_validate(item) for item in transactions],
            total=total,
        )

    async def subscribe(
        self,
        db: AsyncSession,
        payload: SubscribeRequest,
    ) -> SubscribeResponse:
        user = await self._resolve_user(db, payload.user_id)
        active = await self._get_active_subscription(db, user.id)

        now = datetime.now(UTC)
        expires_at = now + timedelta(days=PLAN_DURATION_DAYS[payload.plan_name])
        plan_cost = PLAN_PRICING[payload.plan_name]

        if active is None:
            subscription = Subscription(
                user_id=user.id,
                plan_name=payload.plan_name,
                balance=PLAN_INITIAL_BALANCE[payload.plan_name],
                status=SubscriptionStatus.ACTIVE,
                expires_at=expires_at,
            )
            db.add(subscription)
        else:
            active.plan_name = payload.plan_name
            active.status = SubscriptionStatus.ACTIVE
            active.expires_at = expires_at
            active.balance = max(active.balance, PLAN_INITIAL_BALANCE[payload.plan_name])
            subscription = active

        await db.flush()
        await db.refresh(subscription)

        if payload.plan_name != SubscriptionPlanName.FREE and plan_cost > 0:
            await self._record_transaction(
                db,
                user_id=user.id,
                subscription_id=subscription.id,
                transaction_type=BillingTransactionType.SUBSCRIPTION_CHARGE,
                amount=-plan_cost,
                description=(
                    f"Ежемесячное списание за тариф {PLAN_LABELS_RU[payload.plan_name]}"
                ),
                status=BillingTransactionStatus.SUCCESS,
                reference_id=payload.mock_payment_reference,
            )
            subscription.balance = max(Decimal("0.00"), Decimal(str(subscription.balance)) - plan_cost)
            await db.flush()
            await db.refresh(subscription)

        logger.info(
            "Billing.subscribed | user_id={user_id} plan={plan} mock_ref={ref} cost={cost}",
            user_id=user.id,
            plan=payload.plan_name.value,
            ref=payload.mock_payment_reference,
            cost=str(plan_cost),
        )

        return SubscribeResponse(
            subscription=SubscriptionRead.model_validate(subscription),
            message=f"Тариф {PLAN_LABELS_RU[payload.plan_name]} успешно активирован.",
        )

    async def top_up_balance(
        self,
        db: AsyncSession,
        payload: BalanceTopUpRequest,
    ) -> SubscriptionRead:
        user = await self._resolve_user(db, payload.user_id)
        subscription = await self._get_or_create_active_subscription(db, user.id)
        amount = Decimal(str(payload.amount))
        subscription.balance = Decimal(str(subscription.balance)) + amount

        await self._record_transaction(
            db,
            user_id=user.id,
            subscription_id=subscription.id,
            transaction_type=BillingTransactionType.TOP_UP,
            amount=amount,
            description="Пополнение счета банковской картой",
            status=BillingTransactionStatus.SUCCESS,
        )

        if amount >= BONUS_THRESHOLD:
            bonus_amount = (amount * BONUS_RATE).quantize(Decimal("0.01"))
            await self._record_transaction(
                db,
                user_id=user.id,
                subscription_id=subscription.id,
                transaction_type=BillingTransactionType.BONUS,
                amount=bonus_amount,
                description="Бонус за пополнение от 15 000 ₸",
                status=BillingTransactionStatus.SUCCESS,
            )

        await db.flush()
        await db.refresh(subscription)

        logger.info(
            "Billing.top_up | user_id={user_id} amount={amount} balance={balance}",
            user_id=user.id,
            amount=payload.amount,
            balance=str(subscription.balance),
        )
        return SubscriptionRead.model_validate(subscription)

    async def create_deposit_request(
        self,
        db: AsyncSession,
        *,
        user: User,
        amount: Decimal | float,
        receipt_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> DepositRequestResponse:
        """Manual Kaspi/bank deposit with OCR auto-match or PENDING review fallback."""
        from pathlib import Path

        from app.core.config import settings
        from app.services.notification_service import notification_service
        from app.services.ocr_service import extract_kaspi_receipt_data

        amount_value = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount_value <= 0:
            raise ValueError("Deposit amount must be greater than zero.")

        allowed = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "application/pdf": ".pdf",
        }
        extension = allowed.get((content_type or "").lower())
        if extension is None:
            # Fall back to filename extension for browsers that omit MIME.
            lower_name = filename.lower()
            if lower_name.endswith(".png"):
                extension = ".png"
            elif lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
                extension = ".jpg"
            elif lower_name.endswith(".pdf"):
                extension = ".pdf"
            else:
                raise ValueError("Unsupported receipt type. Use PNG, JPG, or PDF.")

        if len(receipt_bytes) > 50 * 1024 * 1024:
            raise ValueError("Receipt file is too large (max 50 MB).")

        organization_id = getattr(user, "company_id", None)
        subscription = await self._get_or_create_active_subscription(db, user.id)

        # OCR / text parse — never blocks the deposit path on parse failures.
        parsed = None
        try:
            parsed = extract_kaspi_receipt_data(receipt_bytes, filename)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Billing.deposit_ocr_swallowed | error={error}",
                error=str(exc),
            )
            parsed = None

        auto_approve = False
        kaspi_tx_id: str | None = None
        if parsed is not None and parsed.is_complete and parsed.amount is not None:
            kaspi_tx_id = str(parsed.transaction_id).strip()
            parsed_amount = Decimal(str(parsed.amount)).quantize(Decimal("0.01"))
            # Exact integer match against the user-declared deposit amount.
            amounts_match = int(parsed_amount) == int(amount_value)
            duplicate = False
            if kaspi_tx_id and amounts_match:
                duplicate = await self._kaspi_reference_exists(db, kaspi_tx_id)
            auto_approve = bool(kaspi_tx_id) and amounts_match and not duplicate
            if kaspi_tx_id and amounts_match and duplicate:
                logger.warning(
                    "Billing.deposit_duplicate_kaspi_ref | reference_id={reference_id}",
                    reference_id=kaspi_tx_id,
                )

        org_segment = str(organization_id) if organization_id else str(user.id)
        receipt_id = uuid.uuid4()
        upload_dir = Path(settings.UPLOADS_DIR) / "billing" / "receipts" / org_segment
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{receipt_id}{extension}"
        destination = upload_dir / stored_name
        destination.write_bytes(receipt_bytes)
        receipt_url = f"/uploads/billing/receipts/{org_segment}/{stored_name}"

        if auto_approve and kaspi_tx_id:
            amount_label = f"{amount_value:,.0f}".replace(",", " ")
            entry = BillingTransaction(
                user_id=user.id,
                organization_id=organization_id,
                subscription_id=subscription.id,
                transaction_type=BillingTransactionType.MANUAL_DEPOSIT,
                amount=amount_value,
                currency=DEFAULT_CURRENCY,
                description=f"Kaspi автопополнение (чек {kaspi_tx_id})",
                receipt_url=receipt_url,
                status=BillingTransactionStatus.APPROVED,
                reference_id=kaspi_tx_id,
            )
            db.add(entry)

            subscription.balance = Decimal(str(subscription.balance)) + amount_value
            await db.flush()
            await db.refresh(entry)

            await notification_service.notify_auto_approved_deposit(
                db,
                organization_id=organization_id,
                actor_user_id=user.id,
                amount=amount_value,
                transaction_id=entry.id,
                kaspi_reference=kaspi_tx_id,
            )
            await db.flush()

            message = f"Баланс автоматически пополнен на {amount_label} ₸ (Чек проверен)"
            logger.info(
                "Billing.deposit_auto_approved | transaction_id={transaction_id} "
                "user_id={user_id} kaspi_ref={kaspi_ref} amount={amount} balance={balance}",
                transaction_id=entry.id,
                user_id=user.id,
                kaspi_ref=kaspi_tx_id,
                amount=str(amount_value),
                balance=str(subscription.balance),
            )
        else:
            entry = BillingTransaction(
                user_id=user.id,
                organization_id=organization_id,
                subscription_id=subscription.id,
                transaction_type=BillingTransactionType.MANUAL_DEPOSIT,
                amount=amount_value,
                currency=DEFAULT_CURRENCY,
                description="Ручное пополнение (ожидает проверки чека)",
                receipt_url=receipt_url,
                status=BillingTransactionStatus.PENDING,
                reference_id=str(receipt_id),
            )
            db.add(entry)
            await db.flush()
            await db.refresh(entry)

            await notification_service.notify_pending_deposit(
                db,
                organization_id=organization_id,
                actor_user_id=user.id,
                amount=amount_value,
                transaction_id=entry.id,
            )
            await db.flush()

            message = "Заявка принята! Баланс обновится после проверки чека оператором."
            logger.info(
                "Billing.deposit_request_pending | transaction_id={transaction_id} "
                "user_id={user_id} organization_id={organization_id} amount={amount} "
                "ocr_complete={ocr_complete}",
                transaction_id=entry.id,
                user_id=user.id,
                organization_id=organization_id,
                amount=str(amount_value),
                ocr_complete=bool(parsed and parsed.is_complete),
            )

        return DepositRequestResponse(
            id=entry.id,
            organization_id=entry.organization_id,
            amount=float(entry.amount),
            currency=entry.currency,
            receipt_url=receipt_url,
            status=entry.status,
            message=message,
            created_at=entry.created_at,
        )

    async def _kaspi_reference_exists(
        self,
        db: AsyncSession,
        reference_id: str,
    ) -> bool:
        """Idempotency guard: reject reuse of an already-recorded Kaspi transfer id."""
        result = await db.execute(
            select(BillingTransaction.id)
            .where(BillingTransaction.reference_id == reference_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def create_subscription(
        self,
        db: AsyncSession,
        payload: SubscriptionCreate,
    ) -> SubscriptionRead:
        user = await self._resolve_user(db, payload.user_id)
        subscription = Subscription(
            user_id=user.id,
            plan_name=payload.plan_name,
            balance=Decimal(str(payload.balance)),
            status=SubscriptionStatus.ACTIVE,
            expires_at=payload.expires_at,
        )
        db.add(subscription)
        await db.flush()
        await db.refresh(subscription)
        return SubscriptionRead.model_validate(subscription)

    async def _record_transaction(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        subscription_id: uuid.UUID | None,
        transaction_type: BillingTransactionType,
        amount: Decimal,
        description: str,
        status: BillingTransactionStatus,
        reference_id: str | None = None,
    ) -> BillingTransaction:
        entry = BillingTransaction(
            user_id=user_id,
            subscription_id=subscription_id,
            transaction_type=transaction_type,
            amount=amount,
            currency=DEFAULT_CURRENCY,
            description=description,
            status=status,
            reference_id=reference_id,
        )
        db.add(entry)
        await db.flush()
        return entry

    async def _calculate_bonus_balance(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Decimal:
        result = await db.execute(
            select(func.coalesce(func.sum(BillingTransaction.amount), 0))
            .where(
                BillingTransaction.user_id == user_id,
                BillingTransaction.transaction_type == BillingTransactionType.BONUS,
                BillingTransaction.status == BillingTransactionStatus.SUCCESS,
            )
        )
        return Decimal(str(result.scalar_one()))

    async def _get_active_subscription(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Subscription | None:
        result = await db.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(Subscription.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _expire_subscription_if_needed(
        self,
        db: AsyncSession,
        subscription: Subscription,
    ) -> Subscription:
        """Mark expired ACTIVE subscriptions under row lock (safe for concurrent reads)."""
        if subscription.expires_at is None or subscription.status != SubscriptionStatus.ACTIVE:
            return subscription
        if subscription.expires_at >= datetime.now(UTC):
            return subscription

        result = await db.execute(
            select(Subscription)
            .where(Subscription.id == subscription.id)
            .with_for_update()
        )
        locked = result.scalar_one()
        if (
            locked.expires_at is not None
            and locked.expires_at < datetime.now(UTC)
            and locked.status == SubscriptionStatus.ACTIVE
        ):
            locked.status = SubscriptionStatus.EXPIRED
            await db.flush()
            logger.warning(
                "Billing.subscription_expired | user_id={user_id} plan={plan}",
                user_id=locked.user_id,
                plan=locked.plan_name.value,
            )
        return locked

    async def _get_or_create_active_subscription(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> Subscription:
        active = await self._get_active_subscription(db, user_id)
        if active is not None:
            return active

        now = datetime.now(UTC)
        subscription = Subscription(
            user_id=user_id,
            plan_name=SubscriptionPlanName.FREE,
            balance=PLAN_INITIAL_BALANCE[SubscriptionPlanName.FREE],
            status=SubscriptionStatus.ACTIVE,
            expires_at=now + timedelta(days=PLAN_DURATION_DAYS[SubscriptionPlanName.FREE]),
        )
        db.add(subscription)
        await db.flush()
        await db.refresh(subscription)
        logger.info("Billing.default_subscription_created | user_id={user_id}", user_id=user_id)
        return subscription

    async def _resolve_user(self, db: AsyncSession, user_id: uuid.UUID | None) -> User:
        if user_id is not None:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise ValueError(f"User '{user_id}' not found")
            return user

        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user is not None:
            return user

        user = User(
            email="demo@platform.local",
            hashed_password="!",
            company_name="Demo Workspace",
        )
        db.add(user)
        await db.flush()
        return user


billing_service = BillingService()


# --- Payment checkout / webhook settlement (org wallet + PaymentInvoice) ---

from app.services.billing.payment_billing_service import (  # noqa: E402
    payment_billing_service,
)


async def create_checkout_session(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user: User,
    item_type: str,
    plan_or_package_id: str,
    success_url: str | None = None,
    cancel_url: str | None = None,
    provider: str = "stripe",
) -> dict:
    return await payment_billing_service.create_checkout_session(
        db,
        org_id=org_id,
        user=user,
        item_type=item_type,
        plan_or_package_id=plan_or_package_id,
        success_url=success_url,
        cancel_url=cancel_url,
        provider=provider,
    )


async def process_successful_payment(
    db: AsyncSession,
    *,
    external_payment_id: str,
    provider: str,
    provider_signature_data: dict | None = None,
) -> bool:
    return await payment_billing_service.process_successful_payment(
        db,
        external_payment_id=external_payment_id,
        provider=provider,
        provider_signature_data=provider_signature_data,
    )
