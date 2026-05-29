"""Modèle alerte (générée par le service d'alerting par seuils)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.machine import Machine

# Types d'alerte (cf. règles de seuils — PLAN.md §3).
TYPE_CPU_HIGH = "cpu_high"
TYPE_MEM_HIGH = "mem_high"
TYPE_DISK_FULL = "disk_full"
TYPE_OFFLINE = "offline"

# Sévérités.
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

# Statuts du cycle de vie.
STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default=STATUS_OPEN, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    machine: Mapped[Machine] = relationship(back_populates="alerts")
