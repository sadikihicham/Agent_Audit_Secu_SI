"""Tests unitaires du service d'alerting (sans base de données)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.alert import (
    Alert,
    SEVERITY_WARNING,
    STATUS_OPEN,
    STATUS_RESOLVED,
    TYPE_CPU_HIGH,
    TYPE_DISK_FULL,
    TYPE_MEM_HIGH,
    TYPE_OFFLINE,
)
from app.models.machine import STATUS_OFFLINE, STATUS_ONLINE, Machine
from app.models.metric import Metric
from app.services import alerting


# ── helpers ──────────────────────────────────────────────────────────────────

def _machine(id_: int = 1, status: str = STATUS_ONLINE) -> Machine:
    m = Machine(name="test", status=status)
    m.id = id_
    m.last_seen_at = datetime.now(timezone.utc)
    return m


def _metric(cpu: float = 50.0, mem: float = 50.0, disk: float = 50.0) -> Metric:
    m = Metric(
        machine_id=1,
        time=datetime.now(timezone.utc),
        cpu_pct=cpu,
        mem_pct=mem,
        disk_pct=disk,
        uptime_s=3600,
    )
    return m


def _db_returning(*rows) -> AsyncMock:
    """Retourne un AsyncMock de session dont scalar/scalars renvoie les valeurs données."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    # scalar() calls return values in sequence
    db.scalar = AsyncMock(side_effect=list(rows) + [None] * 20)
    scalars_result = MagicMock()
    scalars_result.__iter__ = MagicMock(return_value=iter([]))
    db.scalars = AsyncMock(return_value=scalars_result)
    return db


# ── _open_alert ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_alert_creates_when_none_exists() -> None:
    db = _db_returning(None)  # scalar → no existing alert
    with patch.object(alerting, "_publish", new=AsyncMock()):
        await alerting._open_alert(db, 1, TYPE_CPU_HIGH, SEVERITY_WARNING, "msg", 95.0, 90.0)
    db.add.assert_called_once()
    added: Alert = db.add.call_args[0][0]
    assert added.type == TYPE_CPU_HIGH
    assert added.status == STATUS_OPEN


@pytest.mark.asyncio
async def test_open_alert_no_duplicate() -> None:
    existing = Alert(machine_id=1, type=TYPE_CPU_HIGH, severity=SEVERITY_WARNING,
                     message="x", status=STATUS_OPEN)
    db = _db_returning(existing)
    with patch.object(alerting, "_publish", new=AsyncMock()):
        await alerting._open_alert(db, 1, TYPE_CPU_HIGH, SEVERITY_WARNING, "msg", 95.0, 90.0)
    db.add.assert_not_called()


# ── _maybe_resolve ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_maybe_resolve_resolves_open_alert() -> None:
    open_alert = Alert(machine_id=1, type=TYPE_MEM_HIGH, severity=SEVERITY_WARNING,
                       message="x", status=STATUS_OPEN)
    db = _db_returning(open_alert)
    with patch.object(alerting, "_publish", new=AsyncMock()):
        await alerting._maybe_resolve(db, 1, TYPE_MEM_HIGH)
    assert open_alert.status == STATUS_RESOLVED
    assert open_alert.resolved_at is not None


@pytest.mark.asyncio
async def test_maybe_resolve_noop_when_no_alert() -> None:
    db = _db_returning(None)
    with patch.object(alerting, "_publish", new=AsyncMock()):
        await alerting._maybe_resolve(db, 1, TYPE_MEM_HIGH)
    db.add.assert_not_called()


# ── check_threshold_alerts ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disk_full_alert_fires_above_threshold() -> None:
    machine = _machine()
    latest = _metric(cpu=50.0, mem=50.0, disk=95.0)

    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(return_value=None)  # no existing alerts

    scalars_result = MagicMock()
    scalars_result.__iter__ = MagicMock(return_value=iter([latest]))
    db.scalars = AsyncMock(return_value=scalars_result)

    with patch.object(alerting, "_publish", new=AsyncMock()):
        await alerting.check_threshold_alerts(db, machine)

    # db.add was called with a disk_full alert
    added_alerts = [call[0][0] for call in db.add.call_args_list]
    types = [a.type for a in added_alerts]
    assert TYPE_DISK_FULL in types
    assert TYPE_MEM_HIGH not in types


@pytest.mark.asyncio
async def test_cpu_high_requires_n_consecutive_points() -> None:
    """cpu_high only fires when ALL of the last N samples are over threshold."""
    from app.core.config import settings

    machine = _machine()
    n = settings.alert_cpu_consecutive_points
    # Only 2 high samples when N=3 → no alert
    rows = [_metric(cpu=95.0)] * (n - 1)

    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    scalars_result = MagicMock()
    scalars_result.__iter__ = MagicMock(return_value=iter(rows))
    db.scalars = AsyncMock(return_value=scalars_result)

    with patch.object(alerting, "_publish", new=AsyncMock()):
        await alerting.check_threshold_alerts(db, machine)

    added_types = [call[0][0].type for call in db.add.call_args_list]
    assert TYPE_CPU_HIGH not in added_types


# ── check_offline_machines ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_offline_check_marks_silent_machines() -> None:
    stale_machine = _machine(id_=5, status=STATUS_ONLINE)
    stale_machine.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    db = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(return_value=None)  # no existing offline alert
    scalars_result = MagicMock()
    scalars_result.__iter__ = MagicMock(return_value=iter([stale_machine]))
    db.scalars = AsyncMock(return_value=scalars_result)

    with patch.object(alerting, "_publish", new=AsyncMock()):
        await alerting.check_offline_machines(db)

    assert stale_machine.status == STATUS_OFFLINE
    db.commit.assert_awaited_once()
    added_types = [call[0][0].type for call in db.add.call_args_list]
    assert TYPE_OFFLINE in added_types
