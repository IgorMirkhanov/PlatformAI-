"""Tests for organization LLM API key encryption and gateway resolution."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai_keys_service import (
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
)
from app.services.llm.factory import build_gateway_providers


def test_fernet_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", key)
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", raising=False)

    secret = "sk-test-openai-key-abcdef"
    encrypted = encrypt_api_key(secret)
    assert encrypted.startswith("fernet:")
    assert secret not in encrypted
    assert decrypt_api_key(encrypted) == secret


def test_api_key_readable_after_key_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key sealed under the previous key stays readable while it is retired."""
    from cryptography.fernet import Fernet

    old_key = Fernet.generate_key().decode("ascii")
    new_key = Fernet.generate_key().decode("ascii")
    secret = "sk-test-rotation-abcdef"

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", old_key)
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", raising=False)
    sealed_with_old = encrypt_api_key(secret)

    # Rotate: new key active, old key retained read-only.
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", new_key)
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEYS_OLD", old_key)
    assert decrypt_api_key(sealed_with_old) == secret

    # Dropping the retired key makes the row unrecoverable, as expected.
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS_OLD")
    with pytest.raises(Exception):
        decrypt_api_key(sealed_with_old)


def test_mask_api_key() -> None:
    assert mask_api_key("sk-abcdefghijklmnop") == "sk-...mnop"


def test_build_gateway_providers_uses_org_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.llm.providers  # noqa: F401

    org_key = "sk-org-custom-key"
    providers = build_gateway_providers(
        include_unconfigured=False,
        org_api_keys={"openai": org_key},
    )
    openai = next(p for p in providers if getattr(p, "provider_id", None) == "openai")
    assert openai.api_key == org_key


@pytest.mark.asyncio
async def test_build_gateway_providers_for_organization_loads_keys() -> None:
    from app.services.llm.factory import build_gateway_providers_for_organization

    org_id = uuid.uuid4()
    db = MagicMock()
    # ensure_model_cache() would hit the MagicMock session; it only skips the query
    # when a previous test already warmed its module cache, so stub it explicitly
    # to keep this test independent of suite ordering.
    with (
        patch(
            "app.services.ai_keys_service.ai_keys_service.get_active_keys_map",
            new=AsyncMock(return_value={"deepseek": "ds-secret"}),
        ),
        patch(
            "app.services.llm_model_registry.ensure_model_cache",
            new=AsyncMock(return_value=[]),
        ),
    ):
        providers = await build_gateway_providers_for_organization(db, org_id)
    deepseek = next(
        (p for p in providers if getattr(p, "provider_id", None) == "deepseek"),
        None,
    )
    assert deepseek is not None
    assert deepseek.api_key == "ds-secret"
