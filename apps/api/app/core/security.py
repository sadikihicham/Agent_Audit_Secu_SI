"""Primitives de sécurité : hachage de mots de passe, JWT, tokens d'enrôlement.

Deux types de JWT (claim ``type``) :
- ``user``  : portée lecture du dashboard (TTL court).
- ``agent`` : portée ingestion uniquement (TTL long).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Hachage des mots de passe utilisateur (argon2).
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

TOKEN_TYPE_USER = "user"
TOKEN_TYPE_AGENT = "agent"


# ── Mots de passe ───────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT ──────────────────────────────────────────────────────────────────────
def _create_token(subject: str | int, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def create_user_token(subject: str | int) -> str:
    """JWT utilisateur (lecture dashboard), TTL court."""
    return _create_token(
        subject, TOKEN_TYPE_USER, timedelta(minutes=settings.access_token_ttl_minutes)
    )


def create_agent_token(subject: str | int) -> str:
    """JWT agent (ingestion), TTL long."""
    return _create_token(
        subject, TOKEN_TYPE_AGENT, timedelta(days=settings.agent_token_ttl_days)
    )


def decode_token(token: str) -> dict:
    """Décode et valide un JWT (signature + expiration). Lève ``JWTError`` sinon."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])


# ── Tokens d'enrôlement agent ────────────────────────────────────────────────
def generate_enroll_token() -> str:
    """Token d'enrôlement à usage unique, haute entropie (donné en clair une fois)."""
    return secrets.token_urlsafe(32)


def hash_enroll_token(token: str) -> str:
    """Hash déterministe (sha256) pour stockage + recherche du token d'enrôlement.

    Déterministe (et non argon2) car on doit retrouver la machine par le token
    présenté ; l'entropie élevée du token rend ce choix sûr.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
