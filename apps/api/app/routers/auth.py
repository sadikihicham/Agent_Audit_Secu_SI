"""Authentification utilisateur (login dashboard)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.core.security import create_user_token, verify_password
from app.deps import CurrentUser, DbSession
from app.models import User
from app.schemas.auth import Token, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    """Échange email (``username``) + mot de passe contre un JWT utilisateur."""
    user = await db.scalar(select(User).where(User.email == form.username))
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_user_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> User:
    """Retourne l'utilisateur authentifié (valide le JWT user)."""
    return current_user
