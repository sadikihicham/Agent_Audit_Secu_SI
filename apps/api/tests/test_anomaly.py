"""Tests unitaires de la détection d'anomalies (fonction pure `evaluate`)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.models.alert import TYPE_CPU_ANOMALY
from app.models.machine import Machine
from app.services import anomaly


def _stable(value: float, n: int | None = None) -> list[float]:
    """Liste de `n` valeurs ~stables autour de `value` (légère variation déterministe)."""
    n = n or (settings.anomaly_window)
    return [value + (0.5 if i % 2 else -0.5) for i in range(n)]


# ── evaluate : cas de base ────────────────────────────────────────────────────

def test_cold_start_returns_none() -> None:
    """Pas assez d'historique → pas de détection."""
    assert anomaly.evaluate([10.0, 11.0, 9.0]) is None


def test_normal_value_not_flagged() -> None:
    # base stable ~10 %, dernier point ~10 % → pas d'anomalie
    values = [10.5, 10.0] + _stable(10.0)
    v = anomaly.evaluate(values)
    assert v is not None
    assert v.is_anomaly is False


def test_high_spike_flagged() -> None:
    # base stable ~10 %, deux derniers points à 80 % → anomalie haute
    values = [80.0, 80.0] + _stable(10.0)
    v = anomaly.evaluate(values)
    assert v is not None
    assert v.is_anomaly is True
    assert v.direction == "high"
    assert v.score > settings.anomaly_z_threshold


def test_single_anomalous_point_not_enough() -> None:
    """Un seul point anormal (consecutive=2 par défaut) → pas d'anomalie confirmée."""
    assert settings.anomaly_consecutive_points == 2
    values = [80.0, 10.0] + _stable(10.0)  # le 2e point récent est normal
    v = anomaly.evaluate(values)
    assert v is not None
    assert v.is_anomaly is False


def test_low_anomaly_direction() -> None:
    # base stable ~70 %, deux derniers points à 5 % → anomalie basse
    values = [5.0, 5.0] + _stable(70.0)
    v = anomaly.evaluate(values)
    assert v is not None
    assert v.is_anomaly is True
    assert v.direction == "low"


def test_constant_baseline_small_change_not_flagged() -> None:
    """Base parfaitement constante : un écart < abs_floor n'est pas une anomalie."""
    const = [89.6] * settings.anomaly_window
    values = [89.6 + 1.0, 89.6 + 1.0] + const  # +1 pt < abs_floor (5)
    v = anomaly.evaluate(values)
    assert v is not None
    assert v.is_anomaly is False


def test_constant_baseline_large_jump_flagged() -> None:
    """Base constante : un saut ≥ abs_floor est une anomalie."""
    const = [89.6] * settings.anomaly_window
    values = [89.6 + 10.0, 89.6 + 10.0] + const
    v = anomaly.evaluate(values)
    assert v is not None
    assert v.is_anomaly is True


# ── check_anomalies : intégration légère (db mockée) ──────────────────────────

@pytest.mark.asyncio
async def test_check_anomalies_skips_when_too_few_rows() -> None:
    db = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.__iter__ = MagicMock(return_value=iter([]))  # 0 rows
    db.scalars = AsyncMock(return_value=scalars_result)
    db.commit = AsyncMock()

    machine = Machine(name="t", status="online")
    machine.id = 1

    with patch.object(anomaly.alerting, "open_alert", new=AsyncMock()) as op:
        await anomaly.check_anomalies(db, machine)
    op.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_anomalies_opens_alert_on_cpu_spike() -> None:
    from app.models.metric import Metric
    from datetime import datetime, timezone

    # base CPU ~10 %, deux derniers à 85 % → cpu_anomaly attendue
    def _m(cpu: float) -> Metric:
        return Metric(machine_id=1, time=datetime.now(timezone.utc),
                      cpu_pct=cpu, mem_pct=40.0, disk_pct=30.0, uptime_s=1)

    rows = [_m(85.0), _m(85.0)] + [_m(10.0 + (0.5 if i % 2 else -0.5))
                                   for i in range(settings.anomaly_window)]

    db = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.__iter__ = MagicMock(return_value=iter(rows))
    db.scalars = AsyncMock(return_value=scalars_result)
    db.commit = AsyncMock()

    machine = Machine(name="t", status="online")
    machine.id = 1

    opened: list[str] = []

    async def _open(_db, _mid, type_, *a, **k) -> None:
        opened.append(type_)

    async def _resolve(_db, _mid, _type) -> None:
        pass

    with patch.object(anomaly.alerting, "open_alert", new=_open), \
         patch.object(anomaly.alerting, "resolve_alert", new=_resolve):
        await anomaly.check_anomalies(db, machine)

    assert TYPE_CPU_ANOMALY in opened
    db.commit.assert_awaited_once()
