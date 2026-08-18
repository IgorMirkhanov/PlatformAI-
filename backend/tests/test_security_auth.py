"""Unit tests — password hashing, JWT mint/verify, encryption roundtrip."""

from __future__ import annotations

import uuid

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    digest = hash_password("SuperSecret123!")
    assert digest.startswith(("bcrypt:", "sha256:"))
    assert verify_password("SuperSecret123!", digest)
    assert not verify_password("wrong", digest)


def test_jwt_access_token_claims():
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    token = create_access_token(
        subject=user_id,
        company_id=org_id,
        role="OWNER",
        extra_claims={"email": "a@b.c"},
    )
    claims = decode_access_token(token)
    assert claims["sub"] == str(user_id)
    assert claims["company_id"] == str(org_id)
    assert claims["role"] == "OWNER"
    assert claims["typ"] == "access"


def test_jwt_rejects_garbage():
    with pytest.raises(TokenError):
        decode_access_token("not.a.jwt")
