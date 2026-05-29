"""Tests unitaires des primitives de sécurité (sans base de données)."""
from __future__ import annotations

import pytest
from jose import JWTError

from app.core import security


def test_password_hash_and_verify() -> None:
    hashed = security.hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert security.verify_password("s3cret!", hashed) is True
    assert security.verify_password("wrong", hashed) is False


def test_user_token_roundtrip() -> None:
    token = security.create_user_token(42)
    payload = security.decode_token(token)
    assert payload["sub"] == "42"
    assert payload["type"] == security.TOKEN_TYPE_USER


def test_agent_token_roundtrip() -> None:
    token = security.create_agent_token(7)
    payload = security.decode_token(token)
    assert payload["sub"] == "7"
    assert payload["type"] == security.TOKEN_TYPE_AGENT


def test_decode_invalid_token_raises() -> None:
    with pytest.raises(JWTError):
        security.decode_token("not-a-jwt")


def test_enroll_token_hash_is_deterministic_and_hides_value() -> None:
    raw = security.generate_enroll_token()
    assert security.hash_enroll_token(raw) == security.hash_enroll_token(raw)
    assert security.hash_enroll_token(raw) != raw
    assert security.generate_enroll_token() != security.generate_enroll_token()
