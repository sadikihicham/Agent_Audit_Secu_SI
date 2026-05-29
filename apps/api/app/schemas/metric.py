"""Schémas métrique (lecture)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    machine_id: int
    time: datetime
    cpu_pct: float
    mem_pct: float
    disk_pct: float
    uptime_s: int
