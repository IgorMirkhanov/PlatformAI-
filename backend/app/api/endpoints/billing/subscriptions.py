import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.admin import ensure_not_impersonated
from app.core.database import get_db
from app.core.rate_limit import limiter, rate_limit_key_user
from app.core.rbac import Permission, get_current_user, require_permission
from app.models.users import User
from app.schemas.core_schemas import (
    BalanceTopUpRequest,
    BillingStatusResponse,
    BillingTransactionListResponse,
    DepositRequestResponse,
    SubscribeRequest,
    SubscribeResponse,
    SubscriptionRead,
    SystemNotificationListResponse,
)
from app.services.billing_service import billing_service
from app.services.notification_service import notification_service
from app.services.billing.payment_billing_service import payment_billing_service
from app.services.billing.payment_catalog import SUBSCRIPTION_PLANS, TOPUP_PACKAGES
from app.core.config import settings as app_settings
from app.services.stripe_service import StripeNotConfigured, stripe_service
from app.services.tiptop_service import TipTopNotConfigured

router = APIRouter(prefix="/billing", tags=["billing"])


class WalletBalanceResponse(BaseModel):
    organization_id: uuid.UUID
    balance: int
    currency: str = "CREDITS"
    plan_balance_kzt: float | None = None
    message: str = "Organization wallet balance."


class WalletCheckoutRequest(BaseModel):
    amount: float | None = Field(default=None, gt=0, description="Legacy USD top-up amount")
    item_type: str | None = Field(default=None, description="subscription | topup")
    plan_or_package_id: str | None = Field(default=None, description="Catalog package id")
    provider: str = Field(default="stripe")
    success_url: str | None = None
    cancel_url: str | None = None


class CheckoutResponse(BaseModel):
    checkout_url: str
    invoice_id: str | None = None
    url: str | None = None
    id: str | None = None
    amount: float | None = None
    amount_kzt: float | None = None
    currency: str | None = None
    tokens_allocated: int | None = None


class CardTopupRequest(BaseModel):
    amount: float = Field(gt=0, description="Top-up amount (KZT or USD per currency field)")
    currency: str = Field(default="KZT", description="KZT or USD")
    provider: str = Field(default="stripe", description="stripe or tiptop")
    use_saved_card: bool = Field(default=False, description="Charge saved card token / Stripe PM")
    tiptop_token: str | None = Field(default=None, description="TipTop saved card token")
    widget_mode: bool = Field(
        default=False,
        description="TipTop Pay embedded widget (CloudPayments.js) — skip hosted redirect",
    )
    success_url: str | None = None
    cancel_url: str | None = None


class CardTopupResponse(BaseModel):
    status: str
    checkout_url: str | None = None
    payment_url: str | None = None
    invoice_id: str | None = None
    message: str | None = None
    widget_params: dict | None = None


class SavedPaymentMethodResponse(BaseModel):
    provider: str = "tiptop"
    has_saved_card: bool = False
    card_last_four: str | None = None
    card_type: str | None = None


@router.get(
    "/payment-methods/tiptop",
    response_model=SavedPaymentMethodResponse,
    summary="Saved TipTop Pay card for one-click top-up",
)
async def get_saved_tiptop_payment_method(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_READ)),
) -> SavedPaymentMethodResponse:
    org_id = getattr(current_user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    from app.services.billing.payment_method_service import payment_method_service

    row = await payment_method_service.get_default_token(
        db,
        uuid.UUID(str(org_id)),
        provider="tiptop",
    )
    if row is None:
        return SavedPaymentMethodResponse(has_saved_card=False)
    return SavedPaymentMethodResponse(
        has_saved_card=True,
        card_last_four=row.card_last_four,
        card_type=row.card_type,
    )


@router.get(
    "/wallet",
    response_model=WalletBalanceResponse,
    summary="Organization credit wallet balance",
)
async def get_organization_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_READ)),
) -> WalletBalanceResponse:
    """
    Returns the org credit ledger balance (``organization_wallets``).

    Also includes the legacy subscription KZT balance when available, for
    the settings billing UI during the Workspace & Billing migration.
    """
    org_id = getattr(current_user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    org_uuid = uuid.UUID(str(org_id))
    try:
        from app.services.billing.wallet_service import wallet_service

        wallet = await wallet_service.get_or_create_wallet(db, org_uuid)
        plan_balance: float | None = None
        try:
            status_payload = await billing_service.get_billing_status(
                db=db, user_id=current_user.id
            )
            plan_balance = float(status_payload.balance)
        except Exception:
            plan_balance = None
        return WalletBalanceResponse(
            organization_id=org_uuid,
            balance=int(wallet.balance),
            plan_balance_kzt=plan_balance,
        )
    except Exception as exc:
        logger.exception("Billing.wallet_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load wallet balance.",
        ) from exc


@router.get("/status", response_model=BillingStatusResponse)
async def get_billing_status(
    user_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_READ)),
) -> BillingStatusResponse:
    try:
        # Ignore client-supplied user_id unless platform staff.
        target = current_user.id
        if user_id is not None and user_id != current_user.id:
            if not (
                getattr(current_user, "is_superadmin", False)
                or getattr(current_user, "is_support", False)
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot read another user's billing status.",
                )
            target = user_id
        return await billing_service.get_billing_status(db=db, user_id=target)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Billing.status_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load billing status.",
        ) from exc


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe_to_plan(
    payload: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_WRITE)),
    _: User = Depends(ensure_not_impersonated),
) -> SubscribeResponse:
    try:
        # Always bind subscription mutations to the authenticated user.
        payload = payload.model_copy(update={"user_id": current_user.id})
        return await billing_service.subscribe(db=db, payload=payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid subscription payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Billing.subscribe_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process subscription.",
        ) from exc


@router.get("/transactions", response_model=BillingTransactionListResponse)
async def list_billing_transactions(
    user_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    type_group: str | None = Query(
        default=None,
        description="Filter group: topup | llm (LLM Deduction)",
    ),
    transaction_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_READ)),
) -> BillingTransactionListResponse:
    try:
        parsed_type = None
        if transaction_type:
            from app.models.core_models import BillingTransactionType

            try:
                parsed_type = BillingTransactionType(transaction_type.upper())
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid transaction_type: {transaction_type}",
                ) from exc
        return await billing_service.list_transactions(
            db=db,
            user_id=user_id or current_user.id,
            limit=limit,
            offset=offset,
            transaction_type=parsed_type,
            type_group=type_group,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Billing.transactions_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load billing transactions.",
        ) from exc


@router.post("/top-up", response_model=SubscriptionRead)
async def top_up_balance(
    payload: BalanceTopUpRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_WRITE)),
    _: User = Depends(ensure_not_impersonated),
) -> SubscriptionRead:
    if app_settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Direct balance credit is disabled in production. Use POST /billing/topup with a payment provider.",
        )
    try:
        if payload.user_id is None:
            payload = payload.model_copy(update={"user_id": current_user.id})
        return await billing_service.top_up_balance(db=db, payload=payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid top-up payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Billing.top_up_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to top up balance.",
        ) from exc


@router.post(
    "/topup",
    response_model=CardTopupResponse,
    summary="Wallet top-up by card (alias)",
    include_in_schema=True,
)
@router.post(
    "/topup/card",
    response_model=CardTopupResponse,
    summary="Wallet top-up via Stripe or TipTop Pay",
)
@limiter.limit("15/minute", key_func=rate_limit_key_user)
async def topup_by_card(
    request: Request,
    payload: CardTopupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_WRITE)),
    _: User = Depends(ensure_not_impersonated),
) -> CardTopupResponse:
    org_id = getattr(current_user, "company_id", None)
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Active organization is required.",
        )
    org_uuid = uuid.UUID(str(org_id))
    try:
        base = (app_settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
        success = payload.success_url or f"{base}/dashboard/billing?status=success"
        cancel = payload.cancel_url or f"{base}/dashboard/billing?status=cancel"

        result = await payment_billing_service.process_topup(
            db,
            org_id=org_uuid,
            user=current_user,
            amount=payload.amount,
            currency=payload.currency,
            provider=payload.provider,
            use_saved_card=payload.use_saved_card,
            success_url=success,
            cancel_url=cancel,
            tiptop_token=payload.tiptop_token,
            widget_mode=payload.widget_mode,
        )
        return CardTopupResponse(**result)
    except (StripeNotConfigured, TipTopNotConfigured) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Billing.card_topup_error | error={error}", error=str(exc))
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process card top-up.",
        ) from exc


@router.post("/deposit-request", response_model=DepositRequestResponse)
async def create_deposit_request(
    amount: str = Form(..., description="Deposit amount in KZT"),
    receipt: UploadFile = File(..., description="Payment receipt (PNG, JPG, or PDF)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_WRITE)),
    _: User = Depends(ensure_not_impersonated),
) -> DepositRequestResponse:
    """Kaspi deposit with OCR auto-approval when amount + transfer id match.

    The receipt buffer is scanned via ``extract_kaspi_receipt_data`` inside the
    billing service before the ledger row is committed. Successful matches set
    ``APPROVED`` and credit the wallet; otherwise the file is stored under
    ``/uploads/billing/receipts/`` and status stays ``PENDING``.
    """
    try:
        amount_value = Decimal(amount.replace(",", ".").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid deposit amount.",
        ) from exc

    raw = await receipt.read()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Receipt file is empty.",
        )

    try:
        return await billing_service.create_deposit_request(
            db=db,
            user=current_user,
            amount=amount_value,
            receipt_bytes=raw,
            filename=receipt.filename or "receipt.bin",
            content_type=receipt.content_type or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Billing.deposit_request_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit deposit request.",
        ) from exc


@router.get("/notifications", response_model=SystemNotificationListResponse)
async def list_billing_notifications(
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permission.BILLING_READ)),
) -> SystemNotificationListResponse:
    """Admin alert feed for the header notification bell."""
    try:
        return await notification_service.list_recent(
            db,
            organization_id=getattr(current_user, "company_id", None),
            limit=limit,
        )
    except Exception as exc:
        logger.exception("Billing.notifications_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load billing notifications.",
        ) from exc


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    summary="Create payment checkout session (top-up or subscription)",
)
@limiter.limit("10/minute", key_func=rate_limit_key_user)
async def create_wallet_checkout(
    request: Request,
    payload: WalletCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(ensure_not_impersonated),
) -> CheckoutResponse:
    org_id = getattr(current_user, "company_id", None)
    if org_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Active organization is required.")
    org_uuid = uuid.UUID(str(org_id))
    try:
        if payload.item_type and payload.plan_or_package_id:
            from app.services.billing_service import create_checkout_session

            frontend = (getattr(request.app.state, "frontend_url", None) or "").strip()
            success = payload.success_url
            if not success:
                from app.core.config import settings

                base = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
                success = f"{base}/dashboard/billing/success"
            result = await create_checkout_session(
                db,
                org_id=org_uuid,
                user=current_user,
                item_type=payload.item_type,
                plan_or_package_id=payload.plan_or_package_id,
                success_url=success,
                cancel_url=payload.cancel_url,
                provider=payload.provider,
            )
            return CheckoutResponse(
                checkout_url=result["checkout_url"],
                invoice_id=result.get("invoice_id"),
                url=result["checkout_url"],
                amount=result.get("amount"),
                tokens_allocated=result.get("tokens_allocated"),
                currency="USD",
            )

        if payload.amount is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Provide item_type + plan_or_package_id or legacy amount.",
            )

        base = (app_settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
        success = payload.success_url or f"{base}/dashboard/billing?status=success"
        cancel = payload.cancel_url or f"{base}/dashboard/billing?status=cancel"

        result = await payment_billing_service.process_topup(
            db,
            org_id=org_uuid,
            user=current_user,
            amount=float(payload.amount),
            currency="USD",
            provider="stripe",
            success_url=success,
            cancel_url=cancel,
        )
        checkout_url = str(result.get("checkout_url") or result.get("payment_url") or "")
        return CheckoutResponse(
            checkout_url=checkout_url,
            url=checkout_url,
            invoice_id=result.get("invoice_id"),
            amount=float(payload.amount),
            currency="USD",
        )
    except (StripeNotConfigured, TipTopNotConfigured) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Billing.checkout_error | error={error}", error=str(exc))
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create Stripe Checkout session.",
        ) from exc


@router.get("/catalog/topup", summary="Token top-up packages")
async def list_topup_packages() -> dict:
    return {
        "packages": [
            {
                "id": pkg.id,
                "label": pkg.label,
                "amount_usd": float(pkg.amount_usd),
                "tokens_allocated": pkg.tokens_allocated,
            }
            for pkg in TOPUP_PACKAGES.values()
        ]
    }


@router.get("/catalog/subscriptions", summary="Subscription plans")
async def list_subscription_packages() -> dict:
    return {
        "plans": [
            {
                "id": pkg.id,
                "label": pkg.label,
                "amount_usd": float(pkg.amount_usd),
                "tokens_allocated": pkg.tokens_allocated,
                "plan_id": pkg.plan_id,
            }
            for pkg in SUBSCRIPTION_PLANS.values()
        ]
    }


@router.get(
    "/portal",
    response_model=CheckoutResponse,
    summary="Create Stripe Customer Portal session",
)
async def create_billing_portal(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: User = Depends(ensure_not_impersonated),
) -> CheckoutResponse:
    try:
        result = await stripe_service.create_customer_portal(db, current_user)
        return CheckoutResponse(checkout_url=result["url"], url=result["url"])
    except StripeNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Billing.portal_error | error={error}", error=str(exc))
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create Stripe Customer Portal session.",
        ) from exc


@router.post(
    "/webhook",
    summary="Stripe webhook (Checkout top-up + subscription events)",
    include_in_schema=False,
)
async def stripe_billing_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict:
    if not stripe_signature:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing Stripe-Signature")
    payload = await request.body()
    try:
        return await stripe_service.handle_webhook(db, payload, stripe_signature)
    except StripeNotConfigured as exc:
        from app.core.metrics import record_webhook_failure

        record_webhook_failure("stripe")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        from app.core.metrics import record_webhook_failure

        record_webhook_failure("stripe")
        logger.exception("Billing.webhook_error | error={error}", error=str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
