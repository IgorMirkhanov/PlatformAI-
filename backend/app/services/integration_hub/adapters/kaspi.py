"""Kaspi Pay adapter — merchant invoices and payment-status webhooks.

Creates a payment invoice (amount, description, callback URL). Does **not**
verify customer-uploaded Kaspi receipts: that has no official Kaspi API and
is a separate product (architecture §5).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets as pysecrets
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from loguru import logger

from app.core.config import resolve_webhook_base_url
from app.services.integration_hub.http import hub_request
from app.services.integration_hub.payments import PaymentInvoice, PaymentStatusEvent
from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle

DEFAULT_PAYMENT_BASE = "https://pay.kaspi.kz/pay"
_MAX_AMOUNT = Decimal("10000000")
_STATUS_MAP = {
    "paid": "paid",
    "success": "paid",
    "processed": "paid",
    "completed": "paid",
    "ok": "paid",
    "error": "failed",
    "failed": "failed",
    "rejected": "failed",
    "decline": "failed",
    "declined": "failed",
    "cancel": "cancelled",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "expired": "expired",
    "pending": "pending",
    "wait": "pending",
    "waiting": "pending",
    "created": "created",
    "processing": "pending",
}


def kaspi_webhook_public_url(connection_id: UUID) -> str:
    """Public URI Kaspi (or the merchant cabinet) should call for payment status."""
    return f"{resolve_webhook_base_url()}/webhooks/kaspi_pay/{connection_id}"


def _format_amount(amount: float | int | str | Decimal) -> str:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Сумма счёта Kaspi Pay должна быть числом.") from exc
    if value <= 0:
        raise ValueError("Сумма счёта Kaspi Pay должна быть больше нуля.")
    if value > _MAX_AMOUNT:
        raise ValueError("Сумма счёта Kaspi Pay слишком велика.")
    quantized = value.quantize(Decimal("0.01"))
    return f"{quantized:.2f}"


def _canonical_status(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    return _STATUS_MAP.get(key, key or "pending")


def verify_kaspi_signature(*, secret: str, raw_body: bytes, header: str | None) -> bool:
    """HMAC-SHA256 of the raw body. Accepts ``sha256=<hex>`` or bare hex."""
    expected_secret = (secret or "").strip()
    provided = (header or "").strip()
    if not expected_secret or not provided:
        return False
    if provided.lower().startswith("sha256="):
        provided = provided.split("=", 1)[1].strip()
    digest = hmac.new(expected_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if len(provided) != len(digest):
        return False
    return pysecrets.compare_digest(digest, provided)


class KaspiPayHubAdapter:
    """KaspiPayAdapter: merchant API key, createInvoice, payment.updated webhook."""

    provider = "kaspi_pay"

    def _headers(self, secrets: TokenBundle) -> dict[str, str]:
        token = secrets.api_key or ""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Auth"] = token
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _merchant_id(self, secrets: TokenBundle) -> str:
        extra = secrets.extra or {}
        return str(extra.get("merchant_id") or secrets.external_account_id or "").strip()

    def _payment_base(self, secrets: TokenBundle) -> str:
        extra = secrets.extra or {}
        return str(extra.get("payment_base_url") or DEFAULT_PAYMENT_BASE).rstrip("/")

    def _api_base(self, secrets: TokenBundle) -> str:
        extra = secrets.extra or {}
        return str(extra.get("api_base_url") or extra.get("base_url") or "").rstrip("/")

    def _secret_key(self, secrets: TokenBundle) -> str:
        extra = secrets.extra or {}
        return str(extra.get("secret_key") or extra.get("webhook_secret") or "").strip()

    async def connect(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        payload: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        _ = platform_app, http
        merchant_id = str(payload.get("merchant_id") or "").strip()
        token = str(payload.get("merchant_token") or payload.get("api_key") or "").strip()
        if not merchant_id or len(token) < 8:
            raise ValueError("Для Kaspi Pay нужны Merchant ID и merchant token.")
        secret_key = str(payload.get("secret_key") or payload.get("webhook_secret") or "").strip()
        api_base = str(payload.get("api_base_url") or payload.get("base_url") or "").strip().rstrip("/")
        return TokenBundle(
            api_key=token,
            extra={
                "merchant_id": merchant_id,
                "secret_key": secret_key,
                "payment_base_url": str(
                    payload.get("payment_base_url") or DEFAULT_PAYMENT_BASE
                ).rstrip("/"),
                "api_base_url": api_base,
            },
            external_account_id=merchant_id,
        )

    async def test_connection(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
    ) -> bool:
        _ = connection_id
        merchant_id = self._merchant_id(secrets)
        token = secrets.api_key or ""
        if not merchant_id or len(token) < 8:
            return False
        api_base = self._api_base(secrets)
        if not api_base:
            return True
        try:
            response = await http.get(
                f"{api_base}/invoices",
                headers=self._headers(secrets),
                params={"limit": 1},
                timeout=15.0,
            )
        except Exception:
            return False
        return response.status_code not in {401, 403} and response.status_code < 500

    async def refresh(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
    ) -> TokenBundle:
        _ = platform_app, http
        return secrets

    async def bind_event_handlers(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
    ) -> str:
        """Return the status webhook URI. Optional remote API may register it."""
        uri = kaspi_webhook_public_url(connection_id)
        api_base = self._api_base(secrets)
        if not api_base:
            return uri
        try:
            await hub_request(
                http,
                connection_id=connection_id,
                method="POST",
                url=f"{api_base}/webhooks",
                json_body={"url": uri, "events": ["invoice.status_changed", "payment.updated"]},
                headers=self._headers(secrets),
            )
        except Exception as exc:
            logger.warning(
                "KaspiPay.webhook_bind_failed | connection_id={id} error={error}",
                id=connection_id,
                error=str(exc),
            )
        return uri

    async def create_invoice(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        amount: float,
        description: str,
        callback_url: str | None = None,
        order_id: str | None = None,
    ) -> PaymentInvoice:
        amount_str = _format_amount(amount)
        desc = (description or "").strip()[:500]
        order = (order_id or "").strip() or f"inv-{uuid.uuid4().hex[:12]}"
        callback = (callback_url or "").strip() or kaspi_webhook_public_url(connection_id)
        api_base = self._api_base(secrets)
        if api_base:
            return await self._create_via_api(
                secrets=secrets,
                http=http,
                connection_id=connection_id,
                amount_str=amount_str,
                description=desc,
                callback_url=callback,
                order_id=order,
            )
        return self._create_payment_page(
            secrets=secrets,
            amount_str=amount_str,
            description=desc,
            callback_url=callback,
            order_id=order,
        )

    async def _create_via_api(
        self,
        *,
        secrets: TokenBundle,
        http: httpx.AsyncClient,
        connection_id: UUID,
        amount_str: str,
        description: str,
        callback_url: str,
        order_id: str,
    ) -> PaymentInvoice:
        body = {
            "amount": float(amount_str),
            "description": description,
            "callbackUrl": callback_url,
            "callback_url": callback_url,
            "orderId": order_id,
            "merchantId": self._merchant_id(secrets),
        }
        response = await hub_request(
            http,
            connection_id=connection_id,
            method="POST",
            url=f"{self._api_base(secrets)}/invoices",
            json_body=body,
            headers=self._headers(secrets),
        )
        parsed: dict[str, Any] = {}
        try:
            data = response.json()
            if isinstance(data, dict):
                parsed = data
        except Exception:
            parsed = {}
        invoice_id = str(
            parsed.get("id") or parsed.get("invoice_id") or parsed.get("invoiceId") or order_id
        )
        payment_url = parsed.get("paymentUrl") or parsed.get("payment_url") or parsed.get("url")
        status = _canonical_status(parsed.get("status") or "created")
        return PaymentInvoice(
            id=invoice_id,
            amount=amount_str,
            description=description,
            status=status,
            payment_url=str(payment_url) if payment_url else None,
            callback_url=callback_url,
            order_id=order_id,
            external_id=str(parsed.get("kaspi_invoice_id") or parsed.get("external_id") or "")
            or None,
        )

    def _create_payment_page(
        self,
        *,
        secrets: TokenBundle,
        amount_str: str,
        description: str,
        callback_url: str,
        order_id: str,
    ) -> PaymentInvoice:
        merchant_id = self._merchant_id(secrets)
        query = urlencode(
            {
                "service": merchant_id,
                "amount": amount_str,
                "orderId": order_id,
                "desc": description[:120],
                "notifyUrl": callback_url,
            }
        )
        payment_url = f"{self._payment_base(secrets)}?{query}"
        return PaymentInvoice(
            id=order_id,
            amount=amount_str,
            description=description,
            status="created",
            payment_url=payment_url,
            callback_url=callback_url,
            order_id=order_id,
        )

    def parse_incoming_webhook(
        self,
        payload: dict[str, Any],
        *,
        connection_id: UUID | None = None,
    ) -> PaymentStatusEvent:
        data = payload
        nested = payload.get("data")
        if isinstance(nested, dict):
            data = {**nested, **{k: v for k, v in payload.items() if k != "data"}}
        event_name = str(payload.get("event") or payload.get("type") or "payment.updated")
        if event_name in {"webhook.test", "test"}:
            event_name = "payment.updated"
        status = _canonical_status(
            data.get("status") or data.get("paymentStatus") or data.get("state")
        )
        if status == "paid":
            event_name = "payment.paid"
        elif status in {"failed", "cancelled", "expired"}:
            event_name = f"payment.{status}"
        invoice_id = str(
            data.get("invoice_id")
            or data.get("invoiceId")
            or data.get("id")
            or data.get("orderId")
            or data.get("order_id")
            or ""
        )
        order_id = str(data.get("orderId") or data.get("order_id") or invoice_id)
        amount = data.get("amount")
        amount_str = None if amount is None or amount == "" else str(amount)
        transaction_id = str(
            data.get("transactionId")
            or data.get("transaction_id")
            or data.get("kaspi_invoice_id")
            or ""
        ) or None
        return PaymentStatusEvent(
            type=event_name if event_name.startswith("payment.") else "payment.updated",
            connection_id=str(connection_id) if connection_id else None,
            invoice_id=invoice_id,
            order_id=order_id,
            status=status,
            amount=amount_str,
            transaction_id=transaction_id,
            timestamp=str(data.get("paid_at") or data.get("timestamp") or data.get("date") or ""),
            raw=payload if isinstance(payload, dict) else {},
        )

    def verify_webhook_signature(
        self,
        *,
        secrets: TokenBundle,
        raw_body: bytes,
        signature_header: str | None,
    ) -> bool:
        return verify_kaspi_signature(
            secret=self._secret_key(secrets),
            raw_body=raw_body,
            header=signature_header,
        )

    def merchant_matches(self, secrets: TokenBundle, payload: dict[str, Any]) -> bool:
        expected = self._merchant_id(secrets)
        if not expected:
            return True
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        got = str(
            data.get("merchantId")
            or data.get("merchant_id")
            or data.get("service")
            or payload.get("merchantId")
            or payload.get("merchant_id")
            or ""
        ).strip()
        if not got:
            return True
        return got == expected

    async def request(
        self,
        *,
        connection_id: UUID,
        secrets: TokenBundle,
        method: str,
        url: str,
        http: httpx.AsyncClient,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return await hub_request(
            http,
            connection_id=connection_id,
            method=method,
            url=url,
            json_body=json_body,
            params=params,
            headers=self._headers(secrets),
        )
