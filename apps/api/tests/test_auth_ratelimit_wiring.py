"""TDD : /auth/login doit être protégé par le rate-limiter AVANT toute requête DB
(429 dès le seuil atteint, jamais de vérification d'identifiants après blocage ;
un succès réinitialise le compteur)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.ratelimit import LoginRateLimiter
from app.routers import auth as auth_router
from tests.test_ratelimit import _FakeSortedSetRedis


def _form(username: str = "admin@guardianops.ai", password: str = "wrong") -> SimpleNamespace:
    return SimpleNamespace(username=username, password=password)


def _request(ip: str = "9.9.9.9") -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=ip))


def _db_returning(user) -> AsyncMock:
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=user)
    return db


@pytest.mark.asyncio
async def test_login_blocked_after_max_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    monkeypatch.setattr(auth_router, "login_rate_limiter", limiter)
    request = _request("9.9.9.9")
    form = _form()

    for _ in range(5):
        with pytest.raises(HTTPException) as exc:
            await auth_router.login(form, _db_returning(None), request)
        assert exc.value.status_code == 401

    # 6e tentative : bloquée par le rate-limiter, AVANT toute requête DB.
    db = _db_returning(None)
    with pytest.raises(HTTPException) as exc:
        await auth_router.login(form, db, request)
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
    db.scalar.assert_not_called()


@pytest.mark.asyncio
async def test_login_failures_from_other_ip_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    monkeypatch.setattr(auth_router, "login_rate_limiter", limiter)
    form = _form()

    for _ in range(5):
        with pytest.raises(HTTPException):
            await auth_router.login(form, _db_returning(None), _request("9.9.9.9"))

    # Une autre IP n'est pas affectée par les échecs de la première.
    with pytest.raises(HTTPException) as exc:
        await auth_router.login(form, _db_returning(None), _request("1.1.1.1"))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_login_success_resets_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = LoginRateLimiter(_FakeSortedSetRedis(), max_failures=5, window_seconds=300)
    monkeypatch.setattr(auth_router, "login_rate_limiter", limiter)
    request = _request("2.2.2.2")
    form = _form()
    user = SimpleNamespace(id=1, hashed_password="hash")

    for _ in range(4):
        with pytest.raises(HTTPException) as exc:
            await auth_router.login(form, _db_returning(None), request)
        assert exc.value.status_code == 401

    with patch.object(auth_router, "verify_password", return_value=True):
        token = await auth_router.login(form, _db_returning(user), request)
    assert token.access_token

    # Le succès a réinitialisé le compteur : 4 nouveaux échecs ne bloquent pas encore.
    for _ in range(4):
        with pytest.raises(HTTPException) as exc:
            await auth_router.login(form, _db_returning(None), request)
        assert exc.value.status_code == 401
