"""Détection d'anomalies par machine (z-score robuste médiane/MAD).

Complète l'alerting par seuils : une valeur peut être « anormale » pour une
machine donnée bien en dessous des 90 % absolus (ex. CPU à 60 % sur une machine
qui tourne d'habitude à 10 %). On compare chaque métrique à la base de référence
*propre à la machine* (sa propre histoire récente).

Méthode : z-score robuste basé sur la médiane et le MAD (median absolute
deviation), insensible aux valeurs extrêmes et sans entraînement ni état :

    z = 0.6745 × (x − médiane) / MAD

Une anomalie est déclarée si les `consecutive` derniers points dépassent le
seuil de z (dans la même direction). Repli si la base est ~constante (MAD≈0) :
on exige un écart absolu minimum (`anomaly_abs_floor`).

Les alertes (`cpu_anomaly`, `mem_anomaly`, `disk_anomaly`) réutilisent les
primitives idempotentes du service d'alerting (open_alert / resolve_alert).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.alert import (
    SEVERITY_WARNING,
    TYPE_CPU_ANOMALY,
    TYPE_DISK_ANOMALY,
    TYPE_MEM_ANOMALY,
)
from app.models.machine import Machine
from app.models.metric import Metric
from app.services import alerting

# Constante de mise à l'échelle MAD → écart-type pour une loi normale.
_MAD_SCALE = 0.6745


@dataclass(frozen=True)
class AnomalyVerdict:
    is_anomaly: bool
    value: float
    score: float          # z-score robuste du point le plus récent
    baseline_median: float
    baseline_mad: float
    direction: str        # "high" | "low"


def _robust_z(value: float, median: float, mad: float, stdev: float) -> float:
    """z-score robuste ; repli sur l'écart-type si MAD≈0, sinon écart brut."""
    if mad > 1e-9:
        return _MAD_SCALE * (value - median) / mad
    if stdev > 1e-9:
        return (value - median) / stdev
    # Base parfaitement constante : score = écart absolu (interprété vs abs_floor).
    return value - median


def evaluate(values_desc: list[float]) -> AnomalyVerdict | None:
    """Évalue l'anomalie du point le plus récent.

    `values_desc` : métriques de la machine, du plus récent au plus ancien.
    Retourne None si l'historique est insuffisant (démarrage à froid) ou si la
    détection est impossible.
    """
    window = settings.anomaly_window
    consecutive = settings.anomaly_consecutive_points
    min_samples = settings.anomaly_min_samples
    z_threshold = settings.anomaly_z_threshold
    abs_floor = settings.anomaly_abs_floor

    recent = values_desc[:window]
    # On exclut les `consecutive` points récents de la base pour ne pas la polluer.
    baseline = recent[consecutive:]
    if len(baseline) < min_samples or len(recent) < consecutive:
        return None

    median = statistics.median(baseline)
    abs_devs = [abs(v - median) for v in baseline]
    mad = statistics.median(abs_devs)
    stdev = statistics.pstdev(baseline)

    candidates = recent[:consecutive]
    latest = candidates[0]
    constant_base = mad <= 1e-9 and stdev <= 1e-9

    def _is_anom(v: float) -> bool:
        z = _robust_z(v, median, mad, stdev)
        if constant_base:
            return abs(z) >= abs_floor  # z == écart brut quand base constante
        return abs(z) >= z_threshold

    direction = "high" if latest >= median else "low"
    same_dir = all((v >= median) == (latest >= median) for v in candidates)
    is_anomaly = same_dir and all(_is_anom(v) for v in candidates)

    return AnomalyVerdict(
        is_anomaly=is_anomaly,
        value=round(latest, 1),
        score=round(_robust_z(latest, median, mad, stdev), 2),
        baseline_median=round(median, 1),
        baseline_mad=round(mad, 2),
        direction=direction,
    )


# Métriques surveillées → (attribut du modèle, type d'alerte, libellé).
_METRICS = (
    ("cpu_pct", TYPE_CPU_ANOMALY, "CPU"),
    ("mem_pct", TYPE_MEM_ANOMALY, "Mémoire"),
    ("disk_pct", TYPE_DISK_ANOMALY, "Disque"),
)


async def check_anomalies(db: AsyncSession, machine: Machine) -> None:
    """Évalue les anomalies des métriques de la machine et ouvre/résout les alertes."""
    if not settings.anomaly_enabled:
        return

    rows = list(
        await db.scalars(
            select(Metric)
            .where(Metric.machine_id == machine.id)
            .order_by(Metric.time.desc())
            .limit(settings.anomaly_window)
        )
    )
    if len(rows) < settings.anomaly_min_samples + settings.anomaly_consecutive_points:
        return

    changed = False
    for attr, alert_type, label in _METRICS:
        verdict = evaluate([getattr(r, attr) for r in rows])
        if verdict is None:
            continue
        if verdict.is_anomaly:
            sense = "au-dessus de" if verdict.direction == "high" else "en dessous de"
            message = (
                f"{label} {verdict.value:.1f}% anormal "
                f"(z={verdict.score:+.1f}, {sense} la base "
                f"{verdict.baseline_median:.1f}%±{verdict.baseline_mad:.1f})"
            )
            await alerting.open_alert(
                db, machine.id, alert_type, SEVERITY_WARNING,
                message, verdict.value, None,
            )
        else:
            await alerting.resolve_alert(db, machine.id, alert_type)
        changed = True

    if changed:
        await db.commit()
