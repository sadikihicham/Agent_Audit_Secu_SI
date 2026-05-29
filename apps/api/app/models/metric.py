"""Modèle métrique — hypertable TimescaleDB (séries temporelles).

Clé primaire composite ``(machine_id, time)`` : TimescaleDB exige que la
colonne de partitionnement (``time``) fasse partie de toute contrainte unique.
La conversion en hypertable est effectuée dans la migration.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.machine import Machine


class Metric(Base):
    __tablename__ = "metrics"

    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    cpu_pct: Mapped[float] = mapped_column(Float, nullable=False)
    mem_pct: Mapped[float] = mapped_column(Float, nullable=False)
    disk_pct: Mapped[float] = mapped_column(Float, nullable=False)
    uptime_s: Mapped[int] = mapped_column(BigInteger, nullable=False)

    machine: Mapped[Machine] = relationship(back_populates="metrics")
