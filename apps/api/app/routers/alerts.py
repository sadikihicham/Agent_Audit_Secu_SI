"""Lecture des alertes (auth utilisateur)."""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models.alert import Alert
from app.schemas.alert import AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    db: DbSession,
    _user: CurrentUser,
    status: str | None = Query(default=None, description="Filtrer par statut : open, resolved"),
) -> list[Alert]:
    """Liste les alertes, du plus récent au plus ancien."""
    q = select(Alert).order_by(Alert.created_at.desc())
    if status is not None:
        q = q.where(Alert.status == status)
    return list(await db.scalars(q))
