"""Modèle machine (hôte surveillé par un agent)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.metric import Metric

# Statut dérivé du heartbeat.
STATUS_UNKNOWN = "unknown"
STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Renseigné par l'agent lors de l'enrôlement (inconnu à la création).
    hostname: Mapped[str | None] = mapped_column(String(255))
    os: Mapped[str | None] = mapped_column(String(128))
    # Token d'enrôlement à usage unique, stocké hashé (jamais en clair).
    enroll_token_hash: Mapped[str | None] = mapped_column(String(255), unique=True)
    agent_version: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default=STATUS_UNKNOWN, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    metrics: Mapped[list[Metric]] = relationship(
        back_populates="machine", cascade="all, delete-orphan", passive_deletes=True
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="machine", cascade="all, delete-orphan", passive_deletes=True
    )
