"""TipTop Pay / Freedom Pay (CloudPayments-compatible) acquiring for KZT top-ups."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings


class TipTopNotConfigured(RuntimeError):
    """Raised when TipTop Pay credentials are missing."""


class TipTopService:
    """KZT card payments via TipTop Pay REST API."""

    def enabled(self) -> bool:
        return bool(self._public_id() and self._api_secret())

    def _public_id(self) -> str:
        return (settings.TIPTOP_PUBLIC_ID or "").strip()

    def _api_secret(self) -> str:
        return (settings.TIPTOP_API_SECRET or "").strip()

    def _api_base(self) -> str:
        return (settings.TIPTOP_API_URL or "https://api.tiptoppay.kz").rstrip("/")

    def _auth_header(self) -> str:
        public_id = self._public_id()
        secret = self._api_secret()
        if not public_id or not secret:
            raise TipTopNotConfigured("TIPTOP_PUBLIC_ID / TIPTOP_API_SECRET are not configured")
        token = base64.b64encode(f"{public_id}:{secret}".encode()).decode("ascii")
        return f"Basic {token}"

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, content_hmac: str | None) -> bool:
        secret = (settings.TIPTOP_API_SECRET or "").strip()
        if not secret or not content_hmac:
            return False
        digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("ascii")
        return hmac.compare_digest(expected.strip(), content_hmac.strip())

    async def create_payment_order(
        self,
        *,
        amount_kzt: Decimal,
        invoice_id: uuid.UUID,
        organization_id: uuid.UUID,
        user_email: str,
        description: str,
        success_url: str | None = None,
        fail_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Create TipTop order and return hosted payment page URL.

        Docs: CloudPayments-compatible ``/orders/create`` endpoint.
        """
        if amount_kzt <= 0:
            raise ValueError("amount must be positive")
        if not self.enabled():
            raise TipTopNotConfigured("TipTop Pay is not configured")

        payload = {
            "Amount": float(amount_kzt),
            "Currency": "KZT",
            "Description": description[:255],
            "InvoiceId": str(invoice_id),
            "AccountId": str(organization_id),
            "Email": user_email,
            "JsonData": json.dumps(
                {
                    "organization_id": str(organization_id),
                    "invoice_id": str(invoice_id),
                    "amount_kzt": str(amount_kzt),
                },
                ensure_ascii=False,
            ),
        }
        if success_url:
            payload["SuccessRedirectUrl"] = success_url
        if fail_url:
            payload["FailRedirectUrl"] = fail_url

        url = f"{self._api_base()}/orders/create"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": self._auth_header(),
                    "Content-Type": "application/json",
                },
            )
        if response.status_code >= 400:
            logger.error(
                "TipTop.order_failed | status={status} body={body}",
                status=response.status_code,
                body=response.text[:500],
            )
            raise RuntimeError(f"TipTop order creation failed ({response.status_code})")

        body = response.json()
        if not body.get("Success"):
            message = str(body.get("Message") or body.get("Model") or "TipTop rejected order")
            raise RuntimeError(message)

        model = body.get("Model") or {}
        order_id = str(model.get("Id") or model.get("TransactionId") or "")
        payment_url = str(model.get("Url") or model.get("PaymentUrl") or "")
        if not payment_url:
            # Fallback widget URL when API omits Url (some deployments).
            payment_url = (
                f"https://orders.tiptoppay.kz/d/{self._public_id()}"
                f"?amount={float(amount_kzt)}&currency=KZT&invoiceId={invoice_id}"
                f"&accountId={organization_id}&email={user_email}"
            )

        logger.info(
            "TipTop.order_created | invoice={inv} order={order} amount={amt}",
            inv=invoice_id,
            order=order_id,
            amt=amount_kzt,
        )
        return {
            "order_id": order_id or str(invoice_id),
            "payment_url": payment_url,
            "public_id": self._public_id(),
        }

    async def charge_saved_token(
        self,
        *,
        amount_kzt: Decimal,
        token: str,
        invoice_id: uuid.UUID,
        organization_id: uuid.UUID,
        user_email: str,
        description: str,
    ) -> dict[str, Any]:
        """Charge a previously saved TipTop card token (Cryptogram/Token)."""
        if not token.strip():
            raise ValueError("TipTop card token is required")
        if not self.enabled():
            raise TipTopNotConfigured("TipTop Pay is not configured")

        payload = {
            "Amount": float(amount_kzt),
            "Currency": "KZT",
            "AccountId": str(organization_id),
            "Token": token.strip(),
            "InvoiceId": str(invoice_id),
            "Email": user_email,
            "Description": description[:255],
            "JsonData": json.dumps(
                {
                    "organization_id": str(organization_id),
                    "invoice_id": str(invoice_id),
                }
            ),
        }
        url = f"{self._api_base()}/payments/tokens/charge"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": self._auth_header(),
                    "Content-Type": "application/json",
                },
            )
        body = response.json()
        if response.status_code >= 400 or not body.get("Success"):
            message = str(body.get("Message") or "TipTop token charge failed")
            raise RuntimeError(message)

        model = body.get("Model") or {}
        transaction_id = str(model.get("TransactionId") or model.get("Id") or "")
        return {
            "transaction_id": transaction_id,
            "status": str(model.get("Status") or "Completed"),
            "model": model,
        }

    @staticmethod
    def parse_webhook_payload(raw_body: bytes) -> dict[str, Any] | None:
        try:
            data = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    @staticmethod
    def extract_external_payment_id(payload: dict[str, Any]) -> str | None:
        for key in ("TransactionId", "transaction_id", "Id", "PaymentId"):
            value = payload.get(key)
            if value:
                return str(value)
        model = payload.get("Model")
        if isinstance(model, dict):
            for key in ("TransactionId", "Id"):
                if model.get(key):
                    return str(model[key])
        return None

    @staticmethod
    def is_completed_status(payload: dict[str, Any]) -> bool:
        status = str(payload.get("Status") or payload.get("status") or "").strip()
        if status.lower() in {"completed", "success", "succeeded", "paid"}:
            return True
        model = payload.get("Model")
        if isinstance(model, dict):
            mstatus = str(model.get("Status") or "").strip().lower()
            return mstatus in {"completed", "success", "succeeded", "paid"}
        return False


tiptop_service = TipTopService()
