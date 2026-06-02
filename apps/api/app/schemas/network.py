"""Schémas réseau : ingestion de scan, sortie appareils, synthèse + état."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Ingestion (auth agent) ────────────────────────────────────────────────────


class ScanPort(BaseModel):
    """Un port ouvert rapporté par le scan (Phase B)."""

    port: int = Field(ge=1, le=65535)
    protocol: str = Field(default="tcp", max_length=8)
    service_name: str | None = Field(default=None, max_length=64)
    service_version: str | None = Field(default=None, max_length=128)
    banner: str | None = Field(default=None, max_length=2048)


class ScanInterface(BaseModel):
    """Une interface réseau relevée par SNMP (ifTable)."""

    if_index: int
    name: str | None = Field(default=None, max_length=255)
    mac: str | None = Field(default=None, max_length=17)
    admin_up: bool | None = None
    oper_up: bool | None = None
    speed_bps: int | None = Field(default=None, ge=0)
    mtu: int | None = None
    in_octets: int | None = Field(default=None, ge=0)
    out_octets: int | None = Field(default=None, ge=0)


class ScanDevice(BaseModel):
    """Un appareil tel que rapporté par le scan d'un agent."""

    ip: str = Field(min_length=3, max_length=45)
    mac: str | None = Field(default=None, max_length=17)
    hostname: str | None = Field(default=None, max_length=255)
    vendor: str | None = Field(default=None, max_length=255)
    device_type: str = Field(default="unknown", max_length=64)
    os_guess: str | None = Field(default=None, max_length=128)
    is_gateway: bool = False
    status: Literal["up", "down"] = "up"
    ports: list[ScanPort] = Field(default_factory=list, max_length=512)
    # Enrichissement SNMP (optionnel ; défauts si SNMP désactivé/injoignable).
    sys_descr: str | None = Field(default=None, max_length=1024)
    sys_name: str | None = Field(default=None, max_length=255)
    sys_uptime_secs: int | None = Field(default=None, ge=0)
    sys_location: str | None = Field(default=None, max_length=255)
    sys_contact: str | None = Field(default=None, max_length=255)
    snmp_reachable: bool = False
    interfaces: list[ScanInterface] = Field(default_factory=list, max_length=512)


class ScanRequest(BaseModel):
    # Snapshot complet du périmètre scanné par l'agent (appareils vivants).
    devices: list[ScanDevice] = Field(default_factory=list, max_length=4096)
    cidr: str | None = Field(default=None, max_length=64)


class ScanResponse(BaseModel):
    upserted: int
    new: int
    marked_down: int


class Flow(BaseModel):
    """Une connexion sortante observée par l'agent sur son hôte (Phase C)."""

    remote_ip: str = Field(min_length=3, max_length=45)
    remote_port: int = Field(ge=0, le=65535)
    local_port: int = Field(default=0, ge=0, le=65535)


class FlowsRequest(BaseModel):
    flows: list[Flow] = Field(default_factory=list, max_length=4096)


class FlowsResponse(BaseModel):
    received: int
    flagged: int


class IdsAlert(BaseModel):
    """Une alerte Suricata (extraite d'eve.json) transmise par le forwarder."""

    signature: str = Field(min_length=1, max_length=512)
    category: str | None = Field(default=None, max_length=255)
    # Priorité Suricata : 1 (majeure) … 3 (mineure).
    severity: int = Field(default=3, ge=1, le=5)
    src_ip: str | None = Field(default=None, max_length=45)
    dest_ip: str | None = Field(default=None, max_length=45)
    dest_port: int | None = Field(default=None, ge=0, le=65535)
    proto: str | None = Field(default=None, max_length=16)


class IdsAlertRequest(BaseModel):
    alerts: list[IdsAlert] = Field(default_factory=list, max_length=2048)


class IdsResponse(BaseModel):
    received: int
    recorded: int


# ── Lecture (auth utilisateur) ────────────────────────────────────────────────

# Niveau de risque d'un appareil (densifié en Phase B avec les vulnérabilités).
DeviceRisk = Literal["safe", "vulnerable", "critical"]


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    discovered_by_machine_id: int
    ip: str
    mac: str | None
    hostname: str | None
    vendor: str | None
    device_type: str
    os_guess: str | None
    is_gateway: bool
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    # Enrichissement SNMP (NULL si l'appareil n'a pas répondu en SNMP).
    snmp_reachable: bool = False
    sys_descr: str | None = None
    sys_uptime_secs: int | None = None
    sys_location: str | None = None
    sys_contact: str | None = None
    # Calculés (attributs injectés par le routeur à partir des ports/vulns).
    risk: DeviceRisk = "safe"
    open_ports: int = 0
    vuln_count: int = 0


class InterfaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    if_index: int
    name: str | None
    mac: str | None
    admin_up: bool | None
    oper_up: bool | None
    speed_bps: int | None
    mtu: int | None
    in_octets: int | None
    out_octets: int | None
    last_seen_at: datetime


class PortOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    port: int
    protocol: str
    service_name: str | None
    service_version: str | None
    banner: str | None
    last_seen_at: datetime


VulnSeverity = Literal["info", "low", "medium", "high", "critical"]


class VulnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    port_id: int | None
    cve_id: str | None
    title: str
    severity: VulnSeverity
    cvss: float | None
    description: str | None
    source: str
    detected_at: datetime
    # Renseignés par l'endpoint global /network/vulns (jointure appareil).
    device_ip: str | None = None
    device_hostname: str | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine_id: int
    device_id: int | None
    kind: str
    severity: VulnSeverity
    message: str
    src_ip: str | None
    dst_ip: str | None
    dst_port: int | None
    status: str
    created_at: datetime


# Échelle d'état réseau, de la plus faible à la plus forte gravité.
NetworkState = Literal[
    "indisponible",  # angle mort : aucun scan récent
    "sain",
    "surveille",
    "alarme",
    "sature",
    "critique",
]


class NetworkStateReason(BaseModel):
    """Une raison qui contribue à l'état global (cliquable côté UI)."""

    state: NetworkState
    label: str
    count: int


class NetworkSummary(BaseModel):
    state: NetworkState
    reasons: list[NetworkStateReason]
    total: int
    up: int
    down: int
    gateways: int
    new_last_window: int
    by_type: dict[str, int]
    last_scan_at: datetime | None
    events_recent: int = 0  # événements d'intrusion dans la fenêtre récente
