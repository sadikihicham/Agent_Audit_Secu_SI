"""Service d'ingestion : bulk-insert métriques + mise à jour machine."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.machine import STATUS_ONLINE, Machine
from app.models.metric import Metric
from app.schemas.ingest import MetricSample


async def ingest_metrics(
    db: AsyncSession,
    machine: Machine,
    samples: list[MetricSample],
) -> int:
    """Insère les échantillons en bulk et met à jour last_seen_at / status.

    Utilise ``INSERT … ON CONFLICT DO NOTHING`` pour que les renvois d'une
    offline queue ne provoquent pas d'erreur sur la PK (machine_id, time).
    """
    rows = [
        {
            "machine_id": machine.id,
            "time": s.ts,
            "cpu_pct": s.cpu_pct,
            "mem_pct": s.mem_pct,
            "disk_pct": s.disk_pct,
            "uptime_s": s.uptime_s,
        }
        for s in samples
    ]
    await db.execute(
        insert(Metric).values(rows).on_conflict_do_nothing(index_elements=["machine_id", "time"])
    )
    _touch_machine(machine)
    await db.commit()
    return len(rows)


async def record_heartbeat(db: AsyncSession, machine: Machine) -> None:
    _touch_machine(machine)
    await db.commit()


def _touch_machine(machine: Machine) -> None:
    machine.last_seen_at = datetime.now(timezone.utc)
    machine.status = STATUS_ONLINE
