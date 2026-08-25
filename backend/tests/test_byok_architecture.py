"""BYOK crypto + inbound parsers (architecture spec §§2, 5)."""

from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag

from app.core.crypto import derive_aes256_key
from app.services.crypto_service import decrypt_payload, encrypt_payload
from app.services.crm.adapters import AmoCRMAdapter, Bitrix24Adapter, get_crm_adapter
from app.services.webhooks.parsers import parse_greenapi, parse_telegram, parse_wazzup, parse_widget


def test_encrypt_payload_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "a" * 32)
    kek = derive_aes256_key("a" * 32)
    ciphertext, iv, tag = encrypt_payload({"api_key": "sk-test-secret"}, kek)
    assert iv and tag and ciphertext
    recovered = decrypt_payload(ciphertext, iv, tag, kek)
    assert recovered["api_key"] == "sk-test-secret"


def test_decrypt_payload_wrong_tag_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "b" * 32)
    kek = derive_aes256_key("b" * 32)
    ciphertext, iv, tag = encrypt_payload({"api_key": "sk-other"}, kek)
    bad_tag = bytes(reversed(tag))
    with pytest.raises(InvalidTag):
        decrypt_payload(ciphertext, iv, bad_tag, kek)


def test_parsers_extract_reference_and_message_ids() -> None:
    tg = parse_telegram(
        {
            "update_id": 1,
            "message": {
                "message_id": 42,
                "text": "hi",
                "chat": {"id": 100},
                "from": {"id": 777},
            },
        }
    )
    assert tg is not None
    assert tg.reference_id == "777"
    assert tg.external_message_id == "42"

    wz = parse_wazzup({"channelId": "chan-1", "messageId": "m-9", "text": "hello"})
    assert wz is not None
    assert wz.reference_id == "chan-1"

    ga = parse_greenapi(
        {
            "instanceData": {"idInstance": "123456"},
            "idMessage": "true_1",
            "senderData": {"chatId": "7900@c.us"},
            "messageData": {"textMessageData": {"textMessage": "ping"}},
        }
    )
    assert ga is not None
    assert ga.reference_id == "123456"

    widget = parse_widget({"widget_key": "wgt_1", "message_id": "m1", "text": "q"})
    assert widget is not None
    assert widget.reference_id == "wgt_1"


def test_crm_adapter_factory() -> None:
    amo = get_crm_adapter("amocrm")
    bitrix = get_crm_adapter("bitrix24", webhook_url="https://example.bitrix24.ru/rest/1/token/")
    assert isinstance(amo, AmoCRMAdapter)
    assert isinstance(bitrix, Bitrix24Adapter)
    url = amo.authorize_url(subdomain="myco", state="abc")
    assert "myco.amocrm.ru" in url
    assert "client_id" in url
