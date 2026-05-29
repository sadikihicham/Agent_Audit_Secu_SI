"""Service d'alerting par seuils (cf. PLAN.md §3).

Règles MVP :
- cpu_pct > ALERT_CPU_THRESHOLD pendant N points consécutifs → cpu_high (warning)
- mem_pct > ALERT_MEM_THRESHOLD (1 point)                  → mem_high (warning)
- disk_pct > ALERT_DISK_THRESHOLD (1 point)                → disk_full (critical)
- Pas de heartbeat depuis > ALERT_OFFLINE_MINUTES          → offline (critical)

Chaque type ne peut avoir qu'une seule alerte ouverte par machine à la fois.
Les alertes se résolvent automatiquement quand la condition disparaît.
Les événements (ouverture / résolution) sont publiés sur Redis pour le WebSocket.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import redis_client
from app.models.alert import (
    Alert,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    STATUS_OPEN,
    STATUS_RESOLVED,
    TYPE_CPU_HIGH,
    TYPE_DISK_FULL,
    TYPE_MEM_HIGH,
    TYPE_OFFLINE,
)
from app.models.machine import STATUS_OFFLINE, Machine
from app.models.metric import Metric

log = logging.getLogger(__name__)

REDIS_EVENTS_CHANNEL = "guardianops:events"


async def check_threshold_alerts(db: AsyncSession, machine: Machine) -> None:
    """Évaluer les règles de seuil après une ingestion de métriques.

    Appeler après le commit de l'ingestion — les nouvelles lignes sont déjà
    visibles dans la transaction courante.
    """
    n = settings.alert_cpu_consecutive_points
    rows = list(
        await db.scalars(
            select(Metric)
            .where(Metric.machine_id == machine.id)
            .order_by(Metric.time.desc())
            .limit(n)
        )
    )
    if not rows:
        return

    latest = rows[0]

    # cpu_high — N points consécutifs au-dessus du seuil
    if len(rows) >= n and all(r.cpu_pct > settings.alert_cpu_threshold for r in rows):
        await _open_alert(
            db,
            machine.id,
            TYPE_CPU_HIGH,
            SEVERITY_WARNING,
            f"CPU à {latest.cpu_pct:.1f}% sur {n} échantillons consécutifs",
            latest.cpu_pct,
            settings.alert_cpu_threshold,
        )
    else:
        await _maybe_resolve(db, machine.id, TYPE_CPU_HIGH)

    # mem_high — 1 point
    if latest.mem_pct > settings.alert_mem_threshold:
        await _open_alert(
            db,
            machine.id,
            TYPE_MEM_HIGH,
            SEVERITY_WARNING,
            f"Mémoire à {latest.mem_pct:.1f}%",
            latest.mem_pct,
            settings.alert_mem_threshold,
        )
    else:
        await _maybe_resolve(db, machine.id, TYPE_MEM_HIGH)

    # disk_full — 1 point, critique
    if latest.disk_pct > settings.alert_disk_threshold:
        await _open_alert(
            db,
            machine.id,
            TYPE_DISK_FULL,
            SEVERITY_CRITICAL,
            f"Disque à {latest.disk_pct:.1f}%",
            latest.disk_pct,
            settings.alert_disk_threshold,
        )
    else:
        await _maybe_resolve(db, machine.id, TYPE_DISK_FULL)

    # L'agent vient d'envoyer des métriques → résoudre l'alerte offline si présente
    await _maybe_resolve(db, machine.id, TYPE_OFFLINE)

    await db.commit()


async def resolve_offline_if_needed(db: AsyncSession, machine: Machine) -> None:
    """Appeler sur heartbeat : résoudre l'alerte offline le cas échéant."""
    await _maybe_resolve(db, machine.id, TYPE_OFFLINE)
    await db.commit()


async def check_offline_machines(db: AsyncSession) -> None:
    """Tâche périodique : détecter les machines silencieuses depuis trop longtemps."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.alert_offline_minutes)

    silent_machines = list(
        await db.scalars(
            select(Machine).where(
                Machine.last_seen_at.isnot(None),
                Machine.last_seen_at < cutoff,
                Machine.status != STATUS_OFFLINE,
            )
        )
    )

    for m in silent_machines:
        m.status = STATUS_OFFLINE
        await _open_alert(
            db,
            m.id,
            TYPE_OFFLINE,
            SEVERITY_CRITICAL,
            f"Aucun heartbeat depuis {m.last_seen_at.isoformat()}",
            None,
            None,
        )

    if silent_machines:
        await db.commit()


# ── helpers privés ────────────────────────────────────────────────────────────

async def _open_alert(
    db: AsyncSession,
    machine_id: int,
    type_: str,
    severity: str,
    message: str,
    value: float | None,
    threshold: float | None,
) -> None:
    """Ouvrir une alerte uniquement si aucune n'est déjà ouverte pour ce type."""
    existing = await db.scalar(
        select(Alert).where(
            Alert.machine_id == machine_id,
            Alert.type == type_,
            Alert.status == STATUS_OPEN,
        )
    )
    if existing is not None:
        return

    alert = Alert(
        machine_id=machine_id,
        type=type_,
        severity=severity,
        message=message,
        value=value,
        threshold=threshold,
        status=STATUS_OPEN,
    )
    db.add(alert)
    await _publish({"event": "alert.created", "machine_id": machine_id, "type": type_, "severity": severity})


async def _maybe_resolve(db: AsyncSession, machine_id: int, type_: str) -> None:
    """Résoudre l'alerte ouverte de ce type si elle existe."""
    alert = await db.scalar(
        select(Alert).where(
            Alert.machine_id == machine_id,
            Alert.type == type_,
            Alert.status == STATUS_OPEN,
        )
    )
    if alert is None:
        return

    alert.status = STATUS_RESOLVED
    alert.resolved_at = datetime.now(timezone.utc)
    await _publish({"event": "alert.resolved", "machine_id": machine_id, "type": type_})


async def _publish(payload: dict) -> None:
    try:
        await redis_client.publish(REDIS_EVENTS_CHANNEL, json.dumps(payload))
    except Exception:  # noqa: BLE001
        log.warning("Redis publish failed — alerting event dropped: %s", payload)
