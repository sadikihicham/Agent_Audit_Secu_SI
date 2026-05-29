"""Dépendances FastAPI : session DB et authentification (user / agent)."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
)
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import TOKEN_TYPE_AGENT, TOKEN_TYPE_USER, decode_token
from app.models import Machine, User

DbSession = Annotated[AsyncSession, Depends(get_session)]

# Schéma user : intégré au flux "Authorize" de Swagger via /auth/login.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
# Schéma agent : bearer générique (token fourni par l'agent, pas via Swagger).
agent_bearer = HTTPBearer(auto_error=True)

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Identifiants invalides",
    headers={"WWW-Authenticate": "Bearer"},
)


def _subject_id(payload: dict, expected_type: str) -> int:
    if payload.get("type") != expected_type:
        raise _credentials_exc
    sub = payload.get("sub")
    if sub is None:
        raise _credentials_exc
    try:
        return int(sub)
    except (TypeError, ValueError):
        raise _credentials_exc


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    try:
        payload = decode_token(token)
    except JWTError:
        raise _credentials_exc
    user = await db.get(User, _subject_id(payload, TOKEN_TYPE_USER))
    if user is None:
        raise _credentials_exc
    return user


async def get_current_agent(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(agent_bearer)],
    db: DbSession,
) -> Machine:
    try:
        payload = decode_token(creds.credentials)
    except JWTError:
        raise _credentials_exc
    machine = await db.get(Machine, _subject_id(payload, TOKEN_TYPE_AGENT))
    if machine is None:
        raise _credentials_exc
    return machine


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAgent = Annotated[Machine, Depends(get_current_agent)]
