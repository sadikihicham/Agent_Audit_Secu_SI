"""Schémas ingestion de métriques et heartbeat."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MetricSample(BaseModel):
    ts: datetime
    cpu_pct: float = Field(ge=0.0, le=100.0)
    mem_pct: float = Field(ge=0.0, le=100.0)
    disk_pct: float = Field(ge=0.0, le=100.0)
    uptime_s: int = Field(ge=0)


class IngestMetricsRequest(BaseModel):
    # Batch borné : évite les ingestions abusives d'une offline queue non plafonnée.
    samples: list[MetricSample] = Field(min_length=1, max_length=1000)


class IngestMetricsResponse(BaseModel):
    inserted: int


class HeartbeatResponse(BaseModel):
    status: str
