"""KaspiPayAdapter: invoices, payment-status webhook, no receipt OCR."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services.integration_hub.adapters.kaspi import (
    KaspiPayHubAdapter,
    kaspi_webhook_public_url,
    verify_kaspi_signature,
)
from app.services.integration_hub.types import TokenBundle


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _secrets(**extra: object) -> TokenBundle:
    payload = {
        "merchant_id": "m-1",
        "secret_key": "whsec-kaspi",
        "payment_base_url": "https://pay.kaspi.kz/pay",
        **extra,
    }
    return TokenBundle(api_key="kaspi-token-xx", extra=payload, external_account_id="m-1")


def test_adapter_has_no_receipt_verification() -> None:
    adapter = KaspiPayHubAdapter()
    assert not hasattr(adapter, "verify_receipt")
    assert not hasattr(adapter, "verify_kaspi_receipt")
    assert not hasattr(adapter, "check_receipt")


def test_public_webhook_url() -> None:
    cid = uuid.uuid4()
    assert kaspi_webhook_public_url(cid).endswith(f"/webhooks/kaspi_pay/{cid}")


@pytest.mark.asyncio
async def test_create_invoice_payment_page_includes_amount_desc_callback() -> None:
    cid = uuid.uuid4()
    callback = f"https://api.mp.ai/webhooks/kaspi_pay/{cid}"
    async with _mock_client(lambda _r: httpx.Response(404)) as http:
        invoice = await KaspiPayHubAdapter().create_invoice(
            secrets=_secrets(),
            http=http,
            connection_id=cid,
            amount=1500,
            description="Заказ №42",
            callback_url=callback,
            order_id="ord-42",
        )
    assert invoice.amount == "1500.00"
    assert invoice.description == "Заказ №42"
    assert invoice.callback_url == callback
    assert invoice.status == "created"
    assert invoice.payment_url is not None
    assert "amount=1500.00" in invoice.payment_url
    assert "orderId=ord-42" in invoice.payment_url
    assert "notifyUrl=" in invoice.payment_url
    assert "service=m-1" in invoice.payment_url


@pytest.mark.asyncio
async def test_create_invoice_via_remote_api() -> None:
    cid = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/invoices")
        body = json.loads(request.content.decode())
        assert body["amount"] == 250.5
        assert body["description"] == "Абонемент"
        assert body["callbackUrl"].endswith(f"/webhooks/kaspi_pay/{cid}")
        assert request.headers.get("X-Auth") == "kaspi-token-xx"
        return httpx.Response(
            201,
            json={"id": "inv-9", "paymentUrl": "https://pay.kaspi.kz/i/inv-9", "status": "pending"},
        )

    secrets = _secrets(api_base_url="https://merchant.example/api/v1")
    async with _mock_client(handler) as http:
        invoice = await KaspiPayHubAdapter().create_invoice(
            secrets=secrets,
            http=http,
            connection_id=cid,
            amount=250.5,
            description="Абонемент",
        )
    assert invoice.id == "inv-9"
    assert invoice.status == "pending"
    assert invoice.payment_url == "https://pay.kaspi.kz/i/inv-9"
    assert invoice.callback_url.endswith(f"/webhooks/kaspi_pay/{cid}")


@pytest.mark.asyncio
async def test_create_invoice_rejects_non_positive_amount() -> None:
    async with _mock_client(lambda _r: httpx.Response(404)) as http:
        with pytest.raises(ValueError, match="больше нуля"):
            await KaspiPayHubAdapter().create_invoice(
                secrets=_secrets(),
                http=http,
                connection_id=uuid.uuid4(),
                amount=0,
                description="x",
            )


def test_parse_webhook_paid_status() -> None:
    event = KaspiPayHubAdapter().parse_incoming_webhook(
        {
            "orderId": "ord-1",
            "status": "Paid",
            "amount": "1500.00",
            "transactionId": "tx-9",
        },
        connection_id=uuid.uuid4(),
    )
    assert event.type == "payment.paid"
    assert event.status == "paid"
    assert event.order_id == "ord-1"
    assert event.transaction_id == "tx-9"
    assert event.amount == "1500.00"


def test_verify_signature() -> None:
    body = b'{"status":"Paid"}'
    digest = hmac.new(b"whsec-kaspi", body, hashlib.sha256).hexdigest()
    assert verify_kaspi_signature(secret="whsec-kaspi", raw_body=body, header=f"sha256={digest}")
    assert not verify_kaspi_signature(secret="whsec-kaspi", raw_body=body, header="sha256=deadbeef")


@pytest.mark.asyncio
async def test_webhook_bad_signature_is_403(monkeypatch: pytest.MonkeyPatch) -> None:
    cid = uuid.uuid4()
    conn = SimpleNamespace(id=cid, provider="kaspi_pay", organization_id=uuid.uuid4())
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)
    monkeypatch.setattr(
        "app.services.integration_hub.kaspi_webhook.secrets_from_connection_with_vault",
        AsyncMock(return_value=_secrets()),
    )
    queued: list[object] = []
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.enqueue_hub_webhook_job",
        lambda event_id: queued.append(event_id),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.claim_webhook_dedup_key",
        lambda *a, **k: True,
    )
    from app.services.integration_hub.kaspi_webhook import ingest_kaspi_pay_webhook

    raw = json.dumps({"orderId": "1", "status": "Paid"}).encode()
    request = MagicMock()
    request.headers.get = lambda name, default=None: (
        "application/json" if name == "content-type" else None
    )
    request.body = AsyncMock(return_value=raw)
    request.form = AsyncMock(return_value={})
    resp = await ingest_kaspi_pay_webhook(connection_id=cid, request=request, db=db)
    assert resp.status_code == 403
    assert queued == []
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_valid_queues_payment_updated(monkeypatch: pytest.MonkeyPatch) -> None:
    cid = uuid.uuid4()
    conn = SimpleNamespace(id=cid, provider="kaspi_pay", organization_id=uuid.uuid4())
    db = AsyncMock()
    db.get = AsyncMock(return_value=conn)
    event_id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=event_id)
    monkeypatch.setattr(
        "app.services.integration_hub.kaspi_webhook.secrets_from_connection_with_vault",
        AsyncMock(return_value=_secrets()),
    )
    queued: list[object] = []
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.enqueue_hub_webhook_job",
        lambda eid: queued.append(eid),
    )
    monkeypatch.setattr(
        "app.services.integration_hub.webhook_dedup.claim_webhook_dedup_key",
        lambda *a, **k: True,
    )
    from app.services.integration_hub.kaspi_webhook import ingest_kaspi_pay_webhook

    payload = {"orderId": "ord-1", "status": "Paid", "transactionId": "tx-1"}
    raw = json.dumps(payload).encode()
    digest = hmac.new(b"whsec-kaspi", raw, hashlib.sha256).hexdigest()
    request = MagicMock()
    request.headers.get = lambda name, default=None: {
        "content-type": "application/json",
        "x-kaspi-signature": digest,
    }.get(name, default)
    request.body = AsyncMock(return_value=raw)
    resp = await ingest_kaspi_pay_webhook(connection_id=cid, request=request, db=db)
    assert resp.status_code == 200
    assert queued == [event_id]
