"""Point d'entrée FastAPI de GuardianOps AI."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.redis import redis_client
from app.routers import agents, alerts, auth, ingest, machines, ws
from app.services import alerting

log = logging.getLogger(__name__)


async def _offline_check_loop() -> None:
    """Vérifie toutes les 30 s les machines silencieuses et crée des alertes offline."""
    while True:
        await asyncio.sleep(30)
        try:
            async with SessionLocal() as db:
                await alerting.check_offline_machines(db)
        except Exception:  # noqa: BLE001
            log.exception("Offline check loop error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_offline_check_loop())
    yield
    task.cancel()
    await engine.dispose()
    await redis_client.aclose()


def should_expose_docs(environment: str) -> bool:
    """N'exposer /docs, /redoc et /openapi.json qu'en développement."""
    return environment == "development"


_docs_enabled = should_expose_docs(settings.environment)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Plateforme d'audit permanent SI, monitoring et sécurité.",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(machines.router)
app.include_router(agents.router)
app.include_router(ingest.router)
app.include_router(alerts.router)
app.include_router(ws.router)


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
