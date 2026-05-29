"""Endpoints d'ingestion (authentification agent uniquement)."""
from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import CurrentAgent, DbSession
from app.schemas.ingest import (
    HeartbeatResponse,
    IngestMetricsRequest,
    IngestMetricsResponse,
)
from app.services import alerting
from app.services.ingestion import ingest_metrics, record_heartbeat

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post(
    "/metrics",
    response_model=IngestMetricsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_metrics(
    payload: IngestMetricsRequest,
    db: DbSession,
    machine: CurrentAgent,
) -> IngestMetricsResponse:
    """Ingère un batch de métriques (vidange offline queue incluse)."""
    inserted = await ingest_metrics(db, machine, payload.samples)
    await alerting.check_threshold_alerts(db, machine)
    return IngestMetricsResponse(inserted=inserted)


@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_heartbeat(db: DbSession, machine: CurrentAgent) -> HeartbeatResponse:
    """Met à jour last_seen_at et passe le statut machine à 'online'."""
    await record_heartbeat(db, machine)
    await alerting.resolve_offline_if_needed(db, machine)
    return HeartbeatResponse(status="ok")
