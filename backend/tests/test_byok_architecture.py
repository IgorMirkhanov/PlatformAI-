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


@pytest.mark.asyncio
async def test_greenapi_rejects_email_instance_id() -> None:
    from app.services.greenapi_service import GreenApiError, greenapi_service

    with pytest.raises(GreenApiError, match="idInstance"):
        await greenapi_service.assert_authorized("igor.mirkhanov@email.ru", "token-token-token")


@pytest.mark.asyncio
async def test_greenapi_rejects_placeholder_instance_id() -> None:
    from app.services.greenapi_service import GreenApiError, greenapi_service

    with pytest.raises(GreenApiError, match="idInstance"):
        await greenapi_service.assert_authorized("1101234567", "token-token-token")


def test_normalize_greenapi_chat_id_appends_c_us() -> None:
    from app.services.greenapi_service import normalize_greenapi_chat_id

    assert normalize_greenapi_chat_id("79001234567") == "79001234567@c.us"
    assert normalize_greenapi_chat_id("user@instagram") == "user@instagram"


def test_whatsapp_qr_keeps_lid_jid_for_replies() -> None:
    import uuid

    from app.services.inbound.normalizer import normalize_whatsapp_qr, whatsapp_qr_reply_target

    lid = "135450551414931@lid"
    assert whatsapp_qr_reply_target("135450551414931", {"remote_jid": lid}) == lid
    assert whatsapp_qr_reply_target("77017940910", {"remote_jid": "77017940910@s.whatsapp.net"}) == (
        "77017940910@s.whatsapp.net"
    )
    normalized = normalize_whatsapp_qr(
        bot_id=uuid.uuid4(),
        from_phone="135450551414931",
        message_text="Здравствуйте",
        raw_payload={"remote_jid": lid},
    )
    assert normalized.channel_user_id == lid


def test_whatsapp_qr_is_dispatched_from_provider_catch_all() -> None:
    from app.api.endpoints import webhooks as webhooks_mod

    assert "whatsapp-qr" not in webhooks_mod._BYOK_PROVIDERS
    source = open(webhooks_mod.__file__, encoding="utf-8").read()
    assert 'if key in {"whatsapp-qr", "whatsapp_qr"}' in source


def test_instagram_oauth_url_opens_instagram(monkeypatch: pytest.MonkeyPatch) -> None:
    import uuid

    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "INSTAGRAM_APP_ID", "990602627938098")
    monkeypatch.setattr(config_mod.settings, "INSTAGRAM_APP_SECRET", "ig-app-secret")
    monkeypatch.setattr(config_mod.settings, "META_APP_ID", "990602627938098")
    monkeypatch.setattr(config_mod.settings, "META_APP_SECRET", "ig-app-secret")
    monkeypatch.setattr(config_mod.settings, "WEBHOOK_BASE_URL", "http://127.0.0.1")
    monkeypatch.setattr(config_mod.settings, "JWT_SECRET_KEY", "test-jwt-secret-key-for-pytest-suite")

    from app.services.instagram_oauth import build_instagram_authorize_url

    url = build_instagram_authorize_url(bot_id=uuid.uuid4(), user_id=uuid.uuid4())
    assert url.startswith("https://www.instagram.com/oauth/authorize")
    assert "instagram_business_manage_messages" in url
    assert "response_type=code" in url


def test_crm_adapter_factory() -> None:
    amo = get_crm_adapter("amocrm")
    bitrix = get_crm_adapter("bitrix24", webhook_url="https://example.bitrix24.ru/rest/1/token/")
    assert isinstance(amo, AmoCRMAdapter)
    assert isinstance(bitrix, Bitrix24Adapter)
    url = amo.authorize_url(subdomain="myco", state="abc")
    assert "myco.amocrm.ru" in url
    assert "client_id" in url
