"""Lecture du réseau découvert (auth utilisateur)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models.device import Device
from app.models.device_interface import DeviceInterface
from app.models.device_port import DevicePort
from app.models.device_vuln import DeviceVuln
from app.models.network_event import STATUS_ACK, NetworkEvent
from app.schemas.network import (
    DeviceOut,
    EventOut,
    InterfaceOut,
    NetworkSummary,
    PortOut,
    VulnOut,
)
from app.services import network, vuln

router = APIRouter(prefix="/network", tags=["network"])


@router.get("/summary", response_model=NetworkSummary)
async def get_network_summary(db: DbSession, _user: CurrentUser) -> NetworkSummary:
    """État global du réseau + compteurs pour le dashboard."""
    return await network.get_summary(db)


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices(
    db: DbSession,
    _user: CurrentUser,
    type: str | None = Query(default=None, description="Filtrer par type d'appareil"),
    device_status: str | None = Query(
        default=None, alias="status", description="Filtrer par statut : up, down, unknown"
    ),
) -> list[Device]:
    """Liste les appareils découverts (du plus récemment vu au plus ancien)."""
    q = select(Device).order_by(Device.last_seen_at.desc())
    if type is not None:
        q = q.where(Device.device_type == type)
    if device_status is not None:
        q = q.where(Device.status == device_status)
    devices = list(await db.scalars(q))
    await network.enrich_devices(db, devices)
    return devices


@router.get("/devices/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, db: DbSession, _user: CurrentUser) -> Device:
    """Détail d'un appareil découvert (avec risque + compteurs ports/vulns)."""
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Appareil introuvable"
        )
    await network.enrich_devices(db, [device])
    return device


@router.get("/devices/{device_id}/ports", response_model=list[PortOut])
async def list_device_ports(
    device_id: int, db: DbSession, _user: CurrentUser
) -> list[DevicePort]:
    """Ports ouverts d'un appareil (du plus petit numéro au plus grand)."""
    return list(
        await db.scalars(
            select(DevicePort)
            .where(DevicePort.device_id == device_id)
            .order_by(DevicePort.port.asc())
        )
    )


@router.get("/devices/{device_id}/interfaces", response_model=list[InterfaceOut])
async def list_device_interfaces(
    device_id: int, db: DbSession, _user: CurrentUser
) -> list[DeviceInterface]:
    """Interfaces réseau d'un appareil relevées par SNMP (par ifIndex croissant)."""
    return list(
        await db.scalars(
            select(DeviceInterface)
            .where(DeviceInterface.device_id == device_id)
            .order_by(DeviceInterface.if_index.asc())
        )
    )


@router.get("/devices/{device_id}/vulns", response_model=list[VulnOut])
async def list_device_vulns(
    device_id: int, db: DbSession, _user: CurrentUser
) -> list[DeviceVuln]:
    """Vulnérabilités d'un appareil (de la plus grave à la moins grave)."""
    rows = list(
        await db.scalars(
            select(DeviceVuln).where(DeviceVuln.device_id == device_id)
        )
    )
    rows.sort(
        key=lambda v: (vuln.SEVERITY_RANK.get(v.severity, 0), v.detected_at),
        reverse=True,
    )
    return rows


@router.get("/events", response_model=list[EventOut])
async def list_events(
    db: DbSession,
    _user: CurrentUser,
    kind: str | None = Query(default=None, description="Filtrer par type d'événement"),
    severity: str | None = Query(default=None, description="Filtrer par sévérité"),
    event_status: str | None = Query(
        default=None, alias="status", description="Filtrer par statut : open, acknowledged"
    ),
    device_id: int | None = Query(default=None, description="Filtrer par appareil"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[NetworkEvent]:
    """Événements d'intrusion / anomalies réseau (du plus récent au plus ancien)."""
    q = select(NetworkEvent).order_by(NetworkEvent.created_at.desc()).limit(limit)
    if kind is not None:
        q = q.where(NetworkEvent.kind == kind)
    if severity is not None:
        q = q.where(NetworkEvent.severity == severity)
    if event_status is not None:
        q = q.where(NetworkEvent.status == event_status)
    if device_id is not None:
        q = q.where(NetworkEvent.device_id == device_id)
    return list(await db.scalars(q))


@router.post("/events/{event_id}/ack", response_model=EventOut)
async def ack_event(event_id: int, db: DbSession, _user: CurrentUser) -> NetworkEvent:
    """Acquitte un événement (statut → acknowledged)."""
    event = await db.get(NetworkEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Événement introuvable"
        )
    event.status = STATUS_ACK
    await db.commit()
    return event


@router.get("/vulns", response_model=list[VulnOut])
async def list_vulns(
    db: DbSession,
    _user: CurrentUser,
    severity: str | None = Query(
        default=None, description="Filtrer : info, low, medium, high, critical"
    ),
) -> list[DeviceVuln]:
    """Vulnérabilités du parc, enrichies de l'IP/hostname de l'appareil."""
    q = select(DeviceVuln, Device.ip, Device.hostname).join(
        Device, Device.id == DeviceVuln.device_id
    )
    if severity is not None:
        q = q.where(DeviceVuln.severity == severity)
    out: list[DeviceVuln] = []
    for v, ip, hostname in (await db.execute(q)).all():
        v.device_ip = ip
        v.device_hostname = hostname
        out.append(v)
    out.sort(
        key=lambda v: (vuln.SEVERITY_RANK.get(v.severity, 0), v.detected_at),
        reverse=True,
    )
    return out
