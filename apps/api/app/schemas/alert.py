"""Schémas alerte."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine_id: int
    type: str
    severity: str
    message: str
    value: float | None
    threshold: float | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
