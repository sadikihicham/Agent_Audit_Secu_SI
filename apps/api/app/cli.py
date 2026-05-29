"""CLI d'administration minimal.

Créer un utilisateur admin :
    python -m app.cli create-admin <email> <password>
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models import User
from app.models.user import ROLE_ADMIN


async def create_admin(email: str, password: str) -> None:
    async with SessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is not None:
            print(f"Utilisateur {email} déjà présent (id={existing.id}).")
            return
        user = User(email=email, hashed_password=hash_password(password), role=ROLE_ADMIN)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"Admin créé : {email} (id={user.id})")
    await engine.dispose()


def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] != "create-admin":
        print("Usage : python -m app.cli create-admin <email> <password>")
        raise SystemExit(1)
    asyncio.run(create_admin(sys.argv[2], sys.argv[3]))


if __name__ == "__main__":
    main()
