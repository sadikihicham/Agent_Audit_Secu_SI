"""Tests des endpoints de lecture, tickets WS et validation de la config."""
from __future__ import annotations

import re
from datetime import timedelta

import pytest

from app.core.security import TOKEN_TYPE_USER, create_agent_token, decode_token
from app.routers.machines import RANGE_MAP
from app.routers.ws import _TICKET_PREFIX, _TICKET_TTL_S


# ── RANGE_MAP ─────────────────────────────────────────────────────────────────

def test_range_map_keys_and_durations() -> None:
    assert set(RANGE_MAP) == {"1h", "6h", "24h", "7d"}
    assert RANGE_MAP["1h"] == timedelta(hours=1)
    assert RANGE_MAP["6h"] == timedelta(hours=6)
    assert RANGE_MAP["24h"] == timedelta(hours=24)
    assert RANGE_MAP["7d"] == timedelta(days=7)


def test_range_map_ordering() -> None:
    values = list(RANGE_MAP.values())
    assert values == sorted(values)


# ── WebSocket ticket constants ────────────────────────────────────────────────

def test_ws_ticket_prefix_and_ttl() -> None:
    assert _TICKET_PREFIX == "ws_ticket:"
    assert _TICKET_TTL_S == 30


def test_ws_ticket_key_format() -> None:
    """La clé Redis doit être prévisible et sans collision avec d'autres namespaces."""
    import secrets as _s
    ticket = _s.token_urlsafe(16)
    key = f"{_TICKET_PREFIX}{ticket}"
    assert key.startswith("ws_ticket:")
    # Ticket doit être URL-safe (pas d'espaces ni caractères spéciaux)
    assert re.match(r"^[A-Za-z0-9_\-]+$", ticket)


# ── JWT type checks (token decode layer) ─────────────────────────────────────

def test_ws_rejects_agent_token_type() -> None:
    agent_token = create_agent_token(42)
    payload = decode_token(agent_token)
    assert payload.get("type") != TOKEN_TYPE_USER


def test_ws_accepts_user_token_type() -> None:
    from app.core.security import create_user_token
    user_token = create_user_token(1)
    payload = decode_token(user_token)
    assert payload.get("type") == TOKEN_TYPE_USER


def test_ws_rejects_malformed_token() -> None:
    from jose import JWTError
    with pytest.raises(JWTError):
        decode_token("not.a.jwt")


# ── Config : JWT secret validator ─────────────────────────────────────────────

def _run_validator(value: str) -> str:
    """Appelle le validator directement (sans instancier Settings)."""
    from app.core.config import Settings
    return Settings.jwt_secret_must_be_strong(value)


def test_config_rejects_known_weak_secret() -> None:
    from pydantic import ValidationError
    with pytest.raises((ValueError, ValidationError)):
        _run_validator("change-me-in-production")


def test_config_rejects_short_secret() -> None:
    from pydantic import ValidationError
    with pytest.raises((ValueError, ValidationError)):
        _run_validator("short")


def test_config_accepts_strong_secret() -> None:
    import secrets as _s
    strong = _s.token_hex(32)
    assert _run_validator(strong) == strong


# ── Exposition des docs OpenAPI selon l'environnement ─────────────────────────

def test_docs_exposed_only_in_development() -> None:
    from app.main import should_expose_docs

    assert should_expose_docs("development") is True
    assert should_expose_docs("production") is False
    assert should_expose_docs("staging") is False
    assert should_expose_docs("") is False
