"""Point d'entrée FastAPI de GuardianOps AI."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from app.core.redis import redis_client


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Démarrage : rien à initialiser pour l'instant (migrations gérées par Alembic).
    yield
    # Arrêt : fermeture propre des connexions.
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Plateforme d'audit permanent SI, monitoring et sécurité.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness : l'API répond."""
    return {"status": "ok", "service": settings.app_name}


@app.get("/health/ready", tags=["health"])
async def health_ready() -> dict[str, object]:
    """Readiness : vérifie la connectivité base de données et Redis."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc.__class__.__name__}"

    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc.__class__.__name__}"

    ready = all(v == "ok" for v in checks.values())
    return {"ready": ready, "checks": checks}
