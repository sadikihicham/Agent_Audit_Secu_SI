"""Authentification utilisateur (login dashboard)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.core.ratelimit import LoginRateLimiter
from app.core.redis import redis_client
from app.core.security import create_user_token, verify_password
from app.deps import CurrentUser, DbSession
from app.models import User
from app.schemas.auth import Token, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

# Anti brute-force : seul compte admin, devient nécessaire dès l'exposition publique de l'API
# (topologie split, cf. docs/runbook.md). Module-level pour être monkeypatchable en test.
login_rate_limiter = LoginRateLimiter(redis_client)


@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    request: Request,
) -> Token:
    """Échange email (``username``) + mot de passe contre un JWT utilisateur.

    Rate-limité par IP (5 échecs / 5 min, fenêtre glissante) : bloqué → 429 AVANT toute
    requête DB. Un succès réinitialise le compteur.
    """
    ip = request.client.host if request.client else "unknown"
    if await login_rate_limiter.is_blocked(ip):
        retry = await login_rate_limiter.retry_after(ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Réessayez plus tard.",
            headers={"Retry-After": str(retry or login_rate_limiter.window_seconds)},
        )

    user = await db.scalar(select(User).where(User.email == form.username))
    if user is None or not verify_password(form.password, user.hashed_password):
        await login_rate_limiter.register_failure(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await login_rate_limiter.reset(ip)
    return Token(access_token=create_user_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> User:
    """Retourne l'utilisateur authentifié (valide le JWT user)."""
    return current_user
