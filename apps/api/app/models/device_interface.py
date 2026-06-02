"""Modèle device_interface — interface réseau d'un appareil relevée par SNMP.

Renseigné par l'enrichissement SNMP (ifTable) lors d'un scan : nom, statut
admin/opérationnel, débit, MTU et compteurs d'octets in/out par interface.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.device import Device


class DeviceInterface(Base):
    __tablename__ = "device_interfaces"
    __table_args__ = (
        UniqueConstraint("device_id", "if_index", name="uq_device_interface_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    if_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    mac: Mapped[str | None] = mapped_column(String(17))
    admin_up: Mapped[bool | None] = mapped_column(Boolean)
    oper_up: Mapped[bool | None] = mapped_column(Boolean)
    speed_bps: Mapped[int | None] = mapped_column(BigInteger)
    mtu: Mapped[int | None] = mapped_column(Integer)
    in_octets: Mapped[int | None] = mapped_column(BigInteger)
    out_octets: Mapped[int | None] = mapped_column(BigInteger)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    device: Mapped[Device] = relationship(back_populates="interfaces")
