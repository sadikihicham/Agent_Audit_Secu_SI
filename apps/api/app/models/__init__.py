"""Modèles ORM SQLAlchemy.

Importer tous les modèles ici garantit qu'Alembic (via ``Base.metadata``)
et le mapper SQLAlchemy (résolution des relations par nom) les voient tous.
"""
from __future__ import annotations

from app.models.alert import Alert
from app.models.device import Device
from app.models.device_interface import DeviceInterface
from app.models.device_port import DevicePort
from app.models.device_vuln import DeviceVuln
from app.models.machine import Machine
from app.models.metric import Metric
from app.models.network_event import NetworkEvent
from app.models.user import User

__all__ = [
    "Alert",
    "Device",
    "DeviceInterface",
    "DevicePort",
    "DeviceVuln",
    "Machine",
    "Metric",
    "NetworkEvent",
    "User",
]
