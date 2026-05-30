"""Tests unitaires du service d'alerting (sans base de données réelle)."""
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
    return Metric(
        machine_id=1,
        time=datetime.now(timezone.utc),
        cpu_pct=cpu,
        mem_pct=mem,
        disk_pct=disk,
        uptime_s=3600,
    )


def _flow_db(rows, insert_id: int | None = 1, existing_open: Alert | None = None) -> AsyncMock:
    """Session mock : scalars() → rows ; execute() (INSERT) → insert_id ; scalar() → existing_open."""
    db = AsyncMock()
    db.commit = AsyncMock()

    scalars_result = MagicMock()
    scalars_result.__iter__ = MagicMock(return_value=iter(rows))
    db.scalars = AsyncMock(return_value=scalars_result)

    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=insert_id)
    db.execute = AsyncMock(return_value=exec_result)

    db.scalar = AsyncMock(return_value=existing_open)
    return db


# ── open_alert : INSERT ... ON CONFLICT DO NOTHING RETURNING ─────────────────

@pytest.mark.asyncio
async def test_open_alert_publishes_when_inserted() -> None:
    db = _flow_db(rows=[], insert_id=123)  # une ligne a été insérée
    with patch.object(alerting, "_publish", new=AsyncMock()) as pub:
        await alerting.open_alert(db, 1, TYPE_CPU_HIGH, SEVERITY_WARNING, "msg", 95.0, 90.0)
    db.execute.assert_awaited_once()
    pub.assert_awaited_once()
    assert pub.await_args[0][0]["event"] == "alert.created"


@pytest.mark.asyncio
async def test_open_alert_silent_on_conflict() -> None:
    db = _flow_db(rows=[], insert_id=None)  # conflit → aucune ligne insérée
    with patch.object(alerting, "_publish", new=AsyncMock()) as pub:
        await alerting.open_alert(db, 1, TYPE_MEM_HIGH, SEVERITY_WARNING, "msg", 95.0, 90.0)
    db.execute.assert_awaited_once()
    pub.assert_not_awaited()  # idempotent : pas de doublon d'événement


# ── resolve_alert ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_alert_resolves_open_alert() -> None:
    open_alert = Alert(machine_id=1, type=TYPE_MEM_HIGH, severity=SEVERITY_WARNING,
                       message="x", status=STATUS_OPEN)
    db = _flow_db(rows=[], existing_open=open_alert)
    with patch.object(alerting, "_publish", new=AsyncMock()) as pub:
        await alerting.resolve_alert(db, 1, TYPE_MEM_HIGH)
    assert open_alert.status == STATUS_RESOLVED
    assert open_alert.resolved_at is not None
    pub.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_alert_noop_when_no_alert() -> None:
    db = _flow_db(rows=[], existing_open=None)
    with patch.object(alerting, "_publish", new=AsyncMock()) as pub:
        await alerting.resolve_alert(db, 1, TYPE_MEM_HIGH)
    pub.assert_not_awaited()


# ── check_threshold_alerts ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disk_full_alert_fires_above_threshold() -> None:
    machine = _machine()
    latest = _metric(cpu=50.0, mem=50.0, disk=95.0)
    db = _flow_db(rows=[latest])

    published: list[dict] = []

    async def _capture(payload: dict) -> None:
        published.append(payload)

    with patch.object(alerting, "_publish", new=_capture):
        await alerting.check_threshold_alerts(db, machine)

    created = [p["type"] for p in published if p["event"] == "alert.created"]
    assert TYPE_DISK_FULL in created
    assert TYPE_MEM_HIGH not in created
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_cpu_high_requires_n_consecutive_points() -> None:
    """cpu_high ne se déclenche que si TOUS les N derniers points dépassent le seuil."""
    from app.core.config import settings

    machine = _machine()
    n = settings.alert_cpu_consecutive_points
    rows = [_metric(cpu=95.0)] * (n - 1)  # un point de moins que requis
    db = _flow_db(rows=rows)

    published: list[dict] = []

    async def _capture(payload: dict) -> None:
        published.append(payload)

    with patch.object(alerting, "_publish", new=_capture):
        await alerting.check_threshold_alerts(db, machine)

    created = [p["type"] for p in published if p["event"] == "alert.created"]
    assert TYPE_CPU_HIGH not in created


# ── check_offline_machines ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_offline_check_marks_silent_machines() -> None:
    stale = _machine(id_=5, status=STATUS_ONLINE)
    stale.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db = _flow_db(rows=[stale])

    published: list[dict] = []

    async def _capture(payload: dict) -> None:
        published.append(payload)

    with patch.object(alerting, "_publish", new=_capture):
        await alerting.check_offline_machines(db)

    assert stale.status == STATUS_OFFLINE
    db.commit.assert_awaited_once()
    created = [p["type"] for p in published if p["event"] == "alert.created"]
    assert TYPE_OFFLINE in created
