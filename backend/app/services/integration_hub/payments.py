"""KaspiPayAdapter contract — invoices and payment status (architecture §5).

Receipt/check verification of customer-uploaded PDFs is intentionally out of
scope: Kaspi has no official API for that and it needs a separate legal review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import httpx

from app.services.integration_hub.types import PlatformOAuthApp, TokenBundle


@dataclass
class PaymentInvoice:
    id: str
    amount: str
    currency: str = "KZT"
    description: str = ""
    status: str = "created"
    payment_url: str | None = None
    callback_url: str = ""
    order_id: str | None = None
    external_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "amount": self.amount,
            "currency": self.currency,
            "description": self.description,
            "status": self.status,
            "payment_url": self.payment_url,
            "callback_url": self.callback_url,
            "order_id": self.order_id,
            "external_id": self.external_id,
        }


@dataclass
class PaymentStatusEvent:
    """Canonical inbound event produced by ``parseIncomingWebhook()``."""

    type: str = "payment.updated"
    provider: str = "kaspi_pay"
    connection_id: str | None = None
    invoice_id: str = ""
    order_id: str = ""
    status: str = "pending"
    amount: str | None = None
    currency: str = "KZT"
    transaction_id: str | None = None
    timestamp: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "provider": self.provider,
            "connection_id": self.connection_id,
            "invoice_id": self.invoice_id,
            "order_id": self.order_id,
            "status": self.status,
            "amount": self.amount,
            "currency": self.currency,
            "transaction_id": self.transaction_id,
            "timestamp": self.timestamp,
        }


class KaspiPayAdapter(Protocol):
    provider: str

    async def connect(
        self,
        *,
        platform_app: PlatformOAuthApp | None,
        payload: dict[str, Any],
        http: httpx.AsyncClient,
    ) -> TokenBundle: ...

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
    ) -> PaymentInvoice: ...

    def parse_incoming_webhook(
        self,
        payload: dict[str, Any],
        *,
        connection_id: UUID | None = None,
    ) -> PaymentStatusEvent: ...
