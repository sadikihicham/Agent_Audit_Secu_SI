"""Tests du service d'ingestion (unitaires, sans base de données)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.machine import STATUS_ONLINE, Machine
from app.schemas.ingest import MetricSample
from app.services.ingestion import _touch_machine, ingest_metrics, record_heartbeat


def _sample(ts: datetime | None = None) -> MetricSample:
    return MetricSample(
        ts=ts or datetime.now(timezone.utc),
        cpu_pct=42.0,
        mem_pct=60.0,
        disk_pct=30.0,
        uptime_s=3600,
    )


def _make_machine(**kwargs) -> Machine:
    m = Machine(name="test", status="unknown", **kwargs)
    return m


def test_touch_machine_sets_online_and_timestamp() -> None:
    m = _make_machine()
    _touch_machine(m)
    assert m.status == STATUS_ONLINE
    assert m.last_seen_at is not None


@pytest.mark.asyncio
async def test_ingest_metrics_returns_inserted_count() -> None:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    machine = _make_machine()

    samples = [_sample(), _sample()]
    with patch("app.services.ingestion.insert") as mock_insert:  # pg dialect insert
        mock_insert.return_value.values.return_value.on_conflict_do_nothing.return_value = (
            MagicMock()
        )
        inserted = await ingest_metrics(db, machine, samples)

    assert inserted == 2
    db.commit.assert_awaited_once()
    assert machine.status == STATUS_ONLINE


@pytest.mark.asyncio
async def test_record_heartbeat_commits() -> None:
    db = AsyncMock()
    db.commit = AsyncMock()

    machine = _make_machine()

    await record_heartbeat(db, machine)

    db.commit.assert_awaited_once()
    assert machine.status == STATUS_ONLINE


def test_metric_sample_validates_bounds() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MetricSample(ts=datetime.now(timezone.utc), cpu_pct=101.0, mem_pct=0, disk_pct=0, uptime_s=0)
    with pytest.raises(ValidationError):
        MetricSample(ts=datetime.now(timezone.utc), cpu_pct=0, mem_pct=-1.0, disk_pct=0, uptime_s=0)
    with pytest.raises(ValidationError):
        MetricSample(ts=datetime.now(timezone.utc), cpu_pct=0, mem_pct=0, disk_pct=0, uptime_s=-1)
