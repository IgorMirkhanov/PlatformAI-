"""Encryption key rotation — retired keys stay readable, active key is used for writes."""

from __future__ import annotations

import base64
import secrets

import pytest

from app.core.crypto import (
    decrypt_token,
    encrypt_token,
    reset_field_encryptor,
    resolve_retired_key_materials,
)


def _key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


@pytest.fixture(autouse=True)
def _clear_key_cache():
    reset_field_encryptor()
    yield
    reset_field_encryptor()


def test_retired_keys_exclude_active_and_blanks(monkeypatch: pytest.MonkeyPatch) -> None:
    active, retired = _key(), _key()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", active)
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", f" {retired} , ,{active}, {retired}")

    assert resolve_retired_key_materials() == [retired]


def test_no_retired_keys_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", _key())
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", raising=False)
    monkeypatch.delenv("KMS_KEYS", raising=False)

    assert resolve_retired_key_materials() == []


def test_kms_map_supplies_retired_channel_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    old_key, new_key = _key(), _key()
    secret = "telegram-bot-token"

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", old_key)
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", raising=False)
    monkeypatch.delenv("KMS_KEYS", raising=False)
    sealed = encrypt_token(secret)

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new_key)
    monkeypatch.setenv("KMS_KEYS", f'{{"1":"{old_key}","2":"{new_key}"}}')
    reset_field_encryptor()

    assert old_key in resolve_retired_key_materials()
    assert decrypt_token(sealed) == secret


def test_payload_sealed_with_previous_key_still_decrypts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_key, new_key = _key(), _key()
    secret = "bot-token-1234567890"

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", old_key)
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", raising=False)
    sealed = encrypt_token(secret)

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new_key)
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", old_key)
    reset_field_encryptor()

    assert decrypt_token(sealed) == secret


def test_writes_always_use_the_active_key(monkeypatch: pytest.MonkeyPatch) -> None:
    old_key, new_key = _key(), _key()

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new_key)
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", old_key)
    sealed = encrypt_token("fresh-secret")

    # Dropping the retired key must not affect a freshly written payload.
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD")
    reset_field_encryptor()

    assert decrypt_token(sealed) == "fresh-secret"


def test_payload_is_unrecoverable_once_its_key_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_key, new_key = _key(), _key()

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", old_key)
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", raising=False)
    sealed = encrypt_token("orphaned-secret")

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new_key)
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", raising=False)
    reset_field_encryptor()

    with pytest.raises(ValueError):
        decrypt_token(sealed)
