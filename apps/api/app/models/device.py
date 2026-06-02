"""Modèle device — appareil découvert sur le réseau par le scan d'un agent.

À distinguer de ``Machine`` (hôte exécutant un agent GuardianOps) : un device
est n'importe quel appareil vu sur le réseau (routeur, imprimante, IoT,
téléphone…), qu'il porte un agent ou non. Il est rattaché à l'agent qui l'a
découvert (``discovered_by_machine_id``).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.device_interface import DeviceInterface
    from app.models.machine import Machine

# Type d'appareil (heuristique : MAC vendor + hostname + ports).
TYPE_UNKNOWN = "unknown"
TYPE_ROUTER = "router"
TYPE_SERVER = "server"
TYPE_WORKSTATION = "workstation"
TYPE_PRINTER = "printer"
TYPE_PHONE = "phone"
TYPE_IOT = "iot"
TYPE_NAS = "nas"

# Statut de connectivité (dérivé du dernier scan).
STATUS_UNKNOWN = "unknown"
STATUS_UP = "up"
STATUS_DOWN = "down"


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        # Identité stable d'un appareil dans le périmètre d'un agent : son MAC.
        # (NULL distinct sous Postgres → les appareils sans MAC sont dédupliqués
        # par IP côté service.)
        UniqueConstraint("discovered_by_machine_id", "mac", name="uq_devices_machine_mac"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    discovered_by_machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ip: Mapped[str] = mapped_column(String(45), nullable=False)  # IPv4/IPv6
    mac: Mapped[str | None] = mapped_column(String(17))
    hostname: Mapped[str | None] = mapped_column(String(255))
    vendor: Mapped[str | None] = mapped_column(String(255))
    device_type: Mapped[str] = mapped_column(
        String(64), default=TYPE_UNKNOWN, nullable=False
    )
    os_guess: Mapped[str | None] = mapped_column(String(128))
    is_gateway: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=STATUS_UNKNOWN, nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Enrichissement SNMP (NULL tant que l'appareil n'a pas répondu en SNMP).
    snmp_reachable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    sys_descr: Mapped[str | None] = mapped_column(Text)
    sys_uptime_secs: Mapped[int | None] = mapped_column(BigInteger)
    sys_location: Mapped[str | None] = mapped_column(String(255))
    sys_contact: Mapped[str | None] = mapped_column(String(255))

    discovered_by: Mapped[Machine] = relationship()
    interfaces: Mapped[list[DeviceInterface]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
