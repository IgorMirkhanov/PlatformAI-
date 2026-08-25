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
        text = raw_body.decode("utf-8") or ""
        if not text.strip():
            return None
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        try:
            from urllib.parse import parse_qs

            parsed = parse_qs(text, keep_blank_values=True)
            if not parsed:
                return None
            return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}
        except Exception:
            return None

    @staticmethod
    def _parse_json_field(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    @classmethod
    def extract_metadata(cls, payload: dict[str, Any]) -> dict[str, Any]:
        for key in ("Data", "JsonData", "data", "metadata"):
            blob = cls._parse_json_field(payload.get(key))
            if blob:
                return blob
        model = payload.get("Model")
        if isinstance(model, dict):
            for key in ("Data", "JsonData", "data"):
                blob = cls._parse_json_field(model.get(key))
                if blob:
                    return blob
        return {}

    @classmethod
    def extract_card_token(cls, payload: dict[str, Any]) -> str | None:
        for key in ("Token", "token", "RebillId", "rebill_id"):
            value = payload.get(key)
            if value:
                return str(value).strip()
        model = payload.get("Model")
        if isinstance(model, dict):
            for key in ("Token", "token"):
                if model.get(key):
                    return str(model[key]).strip()
        return None

    @classmethod
    def extract_card_last_four(cls, payload: dict[str, Any]) -> str | None:
        for key in ("CardLastFour", "CardLast4", "card_last_four"):
            value = payload.get(key)
            if value:
                raw = str(value).strip()
                return raw[-4:] if len(raw) >= 4 else raw
        return None

    @classmethod
    def extract_card_type(cls, payload: dict[str, Any]) -> str | None:
        for key in ("CardType", "card_type", "PaymentMethod"):
            value = payload.get(key)
            if value:
                return str(value).strip()
        return None

    @classmethod
    def extract_organization_id(cls, payload: dict[str, Any]) -> str | None:
        meta = cls.extract_metadata(payload)
        for key in ("organization_id", "organizationId", "org_id"):
            value = meta.get(key)
            if value:
                return str(value)
        return None

    @classmethod
    def extract_invoice_id(cls, payload: dict[str, Any]) -> str | None:
        for key in ("InvoiceId", "invoice_id", "InvoiceID"):
            value = payload.get(key)
            if value:
                return str(value)
        meta = cls.extract_metadata(payload)
        for key in ("invoice_id", "invoiceId"):
            value = meta.get(key)
            if value:
                return str(value)
        return None

    @classmethod
    def extract_amount(cls, payload: dict[str, Any]) -> Decimal | None:
        for key in ("Amount", "amount"):
            value = payload.get(key)
            if value is not None:
                try:
                    return Decimal(str(value))
                except Exception:
                    pass
        model = payload.get("Model")
        if isinstance(model, dict):
            for key in ("Amount", "amount"):
                value = model.get(key)
                if value is not None:
                    try:
                        return Decimal(str(value))
                    except Exception:
                        pass
        return None

    @classmethod
    def is_pay_event(cls, payload: dict[str, Any]) -> bool:
        """TipTop / CloudPayments successful Pay (Payment) notification."""
        operation = str(
            payload.get("OperationType") or payload.get("operationType") or ""
        ).strip().lower()
        status = str(payload.get("Status") or payload.get("status") or "").strip().lower()

        if operation in {"payment", "pay"}:
            if status in {"completed", "success", "succeeded", "paid", "authorized"}:
                return True
            if not status:
                return cls.is_completed_status(payload)
            return False

        return cls.is_completed_status(payload)

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
