"""Gestion des machines (auth utilisateur)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.security import generate_enroll_token, hash_enroll_token
from app.deps import CurrentUser, DbSession
from app.models import Machine
from app.models.metric import Metric
from app.schemas.machine import MachineCreate, MachineCreated, MachineOut
from app.schemas.metric import MetricOut

router = APIRouter(prefix="/machines", tags=["machines"])

RANGE_MAP: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


async def _get_machine_or_404(db: DbSession, machine_id: int) -> Machine:
    machine = await db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine introuvable")
    return machine


@router.post("", response_model=MachineCreated, status_code=status.HTTP_201_CREATED)
async def create_machine(
    payload: MachineCreate,
    db: DbSession,
    _user: CurrentUser,
) -> MachineCreated:
    """Crée une machine et génère son token d'enrôlement (montré une seule fois)."""
    enroll_token = generate_enroll_token()
    machine = Machine(name=payload.name, enroll_token_hash=hash_enroll_token(enroll_token))
    db.add(machine)
    await db.commit()
    await db.refresh(machine)
    return MachineCreated(machine=MachineOut.model_validate(machine), enroll_token=enroll_token)


@router.get("", response_model=list[MachineOut])
async def list_machines(db: DbSession, _user: CurrentUser) -> list[Machine]:
    """Liste les machines enregistrées."""
    return list(await db.scalars(select(Machine).order_by(Machine.id)))


@router.get("/{machine_id}", response_model=MachineOut)
async def get_machine(machine_id: int, db: DbSession, _user: CurrentUser) -> Machine:
    """Détail d'une machine."""
    return await _get_machine_or_404(db, machine_id)


@router.get("/{machine_id}/metrics", response_model=list[MetricOut])
async def get_metrics(
    machine_id: int,
    db: DbSession,
    _user: CurrentUser,
    range: str = Query(default="1h", pattern="^(1h|6h|24h|7d)$"),
) -> list[Metric]:
    """Série temporelle de métriques pour une machine (du plus ancien au plus récent)."""
    await _get_machine_or_404(db, machine_id)
    since = datetime.now(timezone.utc) - RANGE_MAP[range]
    return list(
        await db.scalars(
            select(Metric)
            .where(Metric.machine_id == machine_id, Metric.time >= since)
            .order_by(Metric.time.asc())
        )
    )
