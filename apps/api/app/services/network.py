"""Service réseau : ingestion des scans + calcul de l'état global du réseau.

L'ingestion fait un upsert des appareils découverts par un agent (clé : MAC
sinon IP, dans le périmètre de l'agent) et marque ``down`` ceux qui n'étaient
pas dans le dernier scan. ``get_summary`` calcule l'état synthétique du réseau
selon une échelle de gravité, enrichie progressivement (Phase B : vulnérabilités,
Phase C : intrusions / saturation).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.device import (
    STATUS_DOWN,
    STATUS_UP,
    Device,
)
from app.models.device_interface import DeviceInterface
from app.models.device_port import DevicePort
from app.models.device_vuln import DeviceVuln
from app.models.machine import Machine
from app.models.network_event import (
    KIND_ARP_SPOOF,
    KIND_IDS_ALERT,
    KIND_NEW_DEVICE,
    KIND_NEW_OPEN_PORT,
    KIND_OUTBOUND_SUSPICIOUS,
    KIND_PORT_SCAN,
    NetworkEvent,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from app.schemas.network import (
    Flow,
    FlowsResponse,
    IdsAlert,
    IdsResponse,
    NetworkStateReason,
    NetworkSummary,
    ScanDevice,
    ScanRequest,
    ScanResponse,
)
from app.services import events, threatintel, vuln

# Ports sensibles : un nouveau port ouvert sur l'un d'eux est de gravité medium.
_SENSITIVE_PORTS = {21, 22, 23, 3389, 445, 3306, 5432, 6379, 1433, 27017, 5900}

# Rang de gravité des états (pour choisir l'état dominant parmi les raisons).
_STATE_RANK = {
    "indisponible": 0,
    "sain": 1,
    "surveille": 2,
    "alarme": 3,
    "sature": 4,
    "critique": 5,
}


async def ingest_scan(
    db: AsyncSession, machine: Machine, payload: ScanRequest
) -> ScanResponse:
    """Upsert des appareils du scan ; marque ``down`` les absents du périmètre."""
    now = datetime.now(timezone.utc)

    existing = list(
        await db.scalars(
            select(Device).where(Device.discovered_by_machine_id == machine.id)
        )
    )
    by_mac = {d.mac: d for d in existing if d.mac}
    by_ip = {d.ip: d for d in existing if not d.mac}
    had_baseline = len(existing) > 0

    touched: set[int] = set()
    present: list[tuple[Device, ScanDevice, bool]] = []
    new_count = 0

    for sd in payload.devices:
        dev = by_mac.get(sd.mac) if sd.mac else by_ip.get(sd.ip)
        is_new = dev is None
        if dev is None:
            dev = Device(
                discovered_by_machine_id=machine.id,
                ip=sd.ip,
                mac=sd.mac,
                first_seen_at=now,
            )
            db.add(dev)
            new_count += 1
            # Indexer pour dédupliquer d'éventuels doublons dans le même batch.
            if sd.mac:
                by_mac[sd.mac] = dev
            else:
                by_ip[sd.ip] = dev

        dev.ip = sd.ip
        if sd.mac:
            dev.mac = sd.mac
        dev.hostname = sd.hostname
        dev.vendor = sd.vendor
        dev.device_type = sd.device_type
        dev.os_guess = sd.os_guess
        dev.is_gateway = sd.is_gateway
        dev.status = sd.status
        dev.last_seen_at = now
        # Enrichissement SNMP : ne réécrase pas les anciennes valeurs si ce scan
        # n'a pas joint l'appareil en SNMP (snmp_reachable=False).
        if sd.snmp_reachable:
            dev.snmp_reachable = True
            dev.sys_descr = sd.sys_descr
            dev.sys_uptime_secs = sd.sys_uptime_secs
            dev.sys_location = sd.sys_location
            dev.sys_contact = sd.sys_contact
        # id est None tant que pas flush ; on suit via l'objet, pas l'id.
        touched.add(id(dev))
        present.append((dev, sd, is_new))

    # Flush pour attribuer les id aux nouveaux appareils avant de lier ports/vulns.
    await db.flush()
    for dev, sd, is_new in present:
        # Émettre les nouveaux ports seulement sur un appareil déjà connu.
        await _sync_ports_and_vulns(
            db, dev, sd, now, emit_new_ports=had_baseline and not is_new
        )
        # Interfaces SNMP : remplacées uniquement si ce scan en a relevé.
        if sd.snmp_reachable and sd.interfaces:
            await _sync_interfaces(db, dev, sd, now)
        if is_new and had_baseline:
            label = f" ({sd.hostname})" if sd.hostname else ""
            await events.record_event(
                db,
                machine_id=machine.id,
                kind=KIND_NEW_DEVICE,
                severity=SEVERITY_LOW,
                message=f"Nouvel appareil détecté : {sd.ip}{label}",
                device_id=dev.id,
                src_ip=sd.ip,
            )

    # ARP spoofing : un même MAC revendiqué par plusieurs IP dans un scan.
    await _detect_arp_spoof(db, machine.id, payload.devices)

    # Appareils connus de cet agent absents du scan courant → hors-ligne.
    marked_down = 0
    for dev in existing:
        if id(dev) not in touched and dev.status != STATUS_DOWN:
            dev.status = STATUS_DOWN
            marked_down += 1

    await db.commit()
    return ScanResponse(
        upserted=len(payload.devices), new=new_count, marked_down=marked_down
    )


async def _detect_arp_spoof(
    db: AsyncSession, machine_id: int, devices: list[ScanDevice]
) -> None:
    """Émet un événement si un même MAC est revendiqué par plusieurs IP."""
    mac_to_ips: dict[str, set[str]] = {}
    for d in devices:
        if d.mac:
            mac_to_ips.setdefault(d.mac, set()).add(d.ip)
    for mac, ips in mac_to_ips.items():
        if len(ips) > 1:
            await events.record_event(
                db,
                machine_id=machine_id,
                kind=KIND_ARP_SPOOF,
                severity=SEVERITY_HIGH,
                message=f"MAC {mac} revendiqué par plusieurs IP : {', '.join(sorted(ips))}",
                details={"mac": mac, "ips": sorted(ips)},
                dedup_window_minutes=settings.network_event_dedup_minutes,
            )


async def ingest_flows(
    db: AsyncSession, machine: Machine, flows: list[Flow]
) -> FlowsResponse:
    """Analyse les flux sortants : IP/port suspects + heuristique de scan de ports."""
    flagged = 0

    # Blocklist (embarquée ∪ feed Redis) chargée une fois pour tout le lot.
    blocklist = await threatintel.load_blocklist()

    # 1) flux vers IP en liste noire / port C2 connu
    for f in flows:
        if f.remote_ip in blocklist:
            verdict = ("critical", "Connexion vers une IP en liste noire")
        else:
            verdict = threatintel.suspicious_port(f.remote_port)
        if verdict is None:
            continue
        severity, reason = verdict
        inserted = await events.record_event(
            db,
            machine_id=machine.id,
            kind=KIND_OUTBOUND_SUSPICIOUS,
            severity=severity,
            message=f"{reason} : {f.remote_ip}:{f.remote_port}",
            dst_ip=f.remote_ip,
            dst_port=f.remote_port,
            dedup_window_minutes=settings.network_event_dedup_minutes,
        )
        if inserted:
            flagged += 1

    # 2) scan de ports : fan-out vers de nombreuses IP distinctes sur un même port
    by_port: dict[int, set[str]] = {}
    for f in flows:
        by_port.setdefault(f.remote_port, set()).add(f.remote_ip)
    for port, ips in by_port.items():
        if len(ips) >= settings.network_portscan_distinct_targets:
            inserted = await events.record_event(
                db,
                machine_id=machine.id,
                kind=KIND_PORT_SCAN,
                severity=SEVERITY_HIGH,
                message=f"Scan de ports probable : {len(ips)} cibles sur le port {port}",
                dst_port=port,
                details={"distinct_targets": len(ips)},
                dedup_window_minutes=settings.network_event_dedup_minutes,
            )
            if inserted:
                flagged += 1

    await db.commit()
    return FlowsResponse(received=len(flows), flagged=flagged)


def _ids_severity(suricata_severity: int) -> str:
    """Mappe la priorité Suricata (1 majeure … 3+ mineure) sur nos sévérités."""
    if suricata_severity <= 1:
        return SEVERITY_HIGH
    if suricata_severity == 2:
        return SEVERITY_MEDIUM
    return SEVERITY_LOW


async def ingest_ids_alerts(
    db: AsyncSession, machine: Machine, alerts: list[IdsAlert]
) -> IdsResponse:
    """Enregistre les alertes d'un IDS Suricata (sidecar) comme événements réseau."""
    recorded = 0
    for a in alerts:
        inserted = await events.record_event(
            db,
            machine_id=machine.id,
            kind=KIND_IDS_ALERT,
            severity=_ids_severity(a.severity),
            message=a.signature,
            src_ip=a.src_ip,
            dst_ip=a.dest_ip,
            dst_port=a.dest_port,
            details={"category": a.category, "proto": a.proto},
            # Pas de dédup : le forwarder ne transmet que les nouvelles lignes
            # d'eve.json (et des signatures distinctes peuvent viser la même cible).
        )
        if inserted:
            recorded += 1
    await db.commit()
    return IdsResponse(received=len(alerts), recorded=recorded)


async def enrich_devices(db: AsyncSession, devices: list[Device]) -> None:
    """Injecte risk / open_ports / vuln_count sur les appareils (attributs non mappés)."""
    if not devices:
        return
    ids = [d.id for d in devices]

    prows = await db.execute(
        select(DevicePort.device_id, func.count())
        .where(DevicePort.device_id.in_(ids))
        .group_by(DevicePort.device_id)
    )
    ports_by_dev = {did: c for did, c in prows.all()}

    vrows = await db.execute(
        select(DeviceVuln.device_id, DeviceVuln.severity).where(
            DeviceVuln.device_id.in_(ids)
        )
    )
    sev_by_dev: dict[int, list[str]] = {}
    for did, sev in vrows.all():
        sev_by_dev.setdefault(did, []).append(sev)

    for d in devices:
        sevs = sev_by_dev.get(d.id, [])
        d.open_ports = ports_by_dev.get(d.id, 0)
        d.vuln_count = len(sevs)
        d.risk = vuln.risk_from_severities(sevs)


async def _sync_ports_and_vulns(
    db: AsyncSession,
    device: Device,
    sd: ScanDevice,
    now: datetime,
    emit_new_ports: bool = False,
) -> None:
    """Recalcule les ports et vulnérabilités d'un appareil à partir du scan.

    Approche « recompute » (delete + insert) : les ports/vulns reflètent
    toujours l'état du dernier scan. Simple et cohérent à l'échelle MVP ;
    l'acquittement de vulnérabilité (statut) est différé.

    Si ``emit_new_ports`` : émet un événement ``new_open_port`` pour chaque port
    absent du scan précédent (heuristique d'intrusion, Phase C).
    """
    prev_ports: set[int] = set()
    if emit_new_ports:
        prev_ports = set(
            await db.scalars(
                select(DevicePort.port).where(DevicePort.device_id == device.id)
            )
        )

    await db.execute(delete(DeviceVuln).where(DeviceVuln.device_id == device.id))
    await db.execute(delete(DevicePort).where(DevicePort.device_id == device.id))

    if emit_new_ports:
        for port in sorted({sp.port for sp in sd.ports} - prev_ports):
            await events.record_event(
                db,
                machine_id=device.discovered_by_machine_id,
                kind=KIND_NEW_OPEN_PORT,
                severity=SEVERITY_MEDIUM if port in _SENSITIVE_PORTS else SEVERITY_LOW,
                message=f"Nouveau port ouvert {port} sur {device.ip}",
                device_id=device.id,
                dst_ip=device.ip,
                dst_port=port,
            )

    if not sd.ports:
        return

    port_objs: list[DevicePort] = []
    for sp in sd.ports:
        po = DevicePort(
            device_id=device.id,
            port=sp.port,
            protocol=sp.protocol,
            service_name=vuln.service_name_for(sp.port, sp.service_name),
            service_version=sp.service_version,
            banner=sp.banner,
            last_seen_at=now,
        )
        db.add(po)
        port_objs.append(po)
    await db.flush()  # attribue les id de ports pour lier les vulns

    port_id_by_num: dict[int, int] = {}
    for po in port_objs:
        port_id_by_num.setdefault(po.port, po.id)

    portlikes = [
        vuln.PortLike(
            port=sp.port,
            service_name=sp.service_name,
            service_version=sp.service_version,
            banner=sp.banner,
        )
        for sp in sd.ports
    ]
    for f in vuln.evaluate(portlikes):
        db.add(
            DeviceVuln(
                device_id=device.id,
                port_id=port_id_by_num.get(f["port"]),
                cve_id=f["cve_id"],
                title=f["title"],
                severity=f["severity"],
                cvss=f["cvss"],
                description=f["description"],
                source=f["source"],
                detected_at=now,
            )
        )


async def _sync_interfaces(
    db: AsyncSession, device: Device, sd: ScanDevice, now: datetime
) -> None:
    """Recalcule les interfaces SNMP d'un appareil (approche delete + insert).

    Comme pour les ports, les interfaces reflètent toujours le dernier scan SNMP.
    Appelée seulement quand le scan a effectivement relevé des interfaces.
    """
    await db.execute(
        delete(DeviceInterface).where(DeviceInterface.device_id == device.id)
    )
    seen: set[int] = set()
    for iface in sd.interfaces:
        # Dédup défensif sur ifIndex (contrainte unique device_id+if_index).
        if iface.if_index in seen:
            continue
        seen.add(iface.if_index)
        db.add(
            DeviceInterface(
                device_id=device.id,
                if_index=iface.if_index,
                name=iface.name,
                mac=iface.mac,
                admin_up=iface.admin_up,
                oper_up=iface.oper_up,
                speed_bps=iface.speed_bps,
                mtu=iface.mtu,
                in_octets=iface.in_octets,
                out_octets=iface.out_octets,
                last_seen_at=now,
            )
        )


async def get_summary(db: AsyncSession) -> NetworkSummary:
    """État synthétique du réseau + compteurs pour le dashboard."""
    total = await db.scalar(select(func.count()).select_from(Device)) or 0
    up = (
        await db.scalar(
            select(func.count()).select_from(Device).where(Device.status == STATUS_UP)
        )
        or 0
    )
    down = (
        await db.scalar(
            select(func.count()).select_from(Device).where(Device.status == STATUS_DOWN)
        )
        or 0
    )
    gateways = (
        await db.scalar(
            select(func.count()).select_from(Device).where(Device.is_gateway.is_(True))
        )
        or 0
    )
    down_gateways = (
        await db.scalar(
            select(func.count())
            .select_from(Device)
            .where(Device.is_gateway.is_(True), Device.status == STATUS_DOWN)
        )
        or 0
    )
    last_scan_at = await db.scalar(select(func.max(Device.last_seen_at)))

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=settings.network_new_device_window_hours)
    new_last_window = (
        await db.scalar(
            select(func.count())
            .select_from(Device)
            .where(Device.first_seen_at >= window_start)
        )
        or 0
    )

    rows = await db.execute(
        select(Device.device_type, func.count()).group_by(Device.device_type)
    )
    by_type = {t: c for t, c in rows.all()}

    # Vulnérabilités : nb d'appareils distincts par sévérité (critique / élevée / moyenne).
    crit_vuln_devices = await _count_devices_with_severity(db, "critical")
    high_vuln_devices = await _count_devices_with_severity(db, "high")
    med_vuln_devices = await _count_devices_with_severity(db, "medium")

    # Événements d'intrusion récents (Phase C) + saturation.
    ev_window = now - timedelta(minutes=settings.network_event_window_minutes)

    async def _count_events(kind: str) -> int:
        return (
            await db.scalar(
                select(func.count())
                .select_from(NetworkEvent)
                .where(NetworkEvent.kind == kind, NetworkEvent.created_at >= ev_window)
            )
            or 0
        )

    arp_events = await _count_events(KIND_ARP_SPOOF)
    outbound_events = await _count_events(KIND_OUTBOUND_SUSPICIOUS)
    portscan_events = await _count_events(KIND_PORT_SCAN)
    new_port_events = await _count_events(KIND_NEW_OPEN_PORT)
    events_recent = (
        await db.scalar(
            select(func.count())
            .select_from(NetworkEvent)
            .where(NetworkEvent.created_at >= ev_window)
        )
        or 0
    )

    sat_window = now - timedelta(minutes=settings.network_saturation_window_minutes)
    recent_new = (
        await db.scalar(
            select(func.count())
            .select_from(Device)
            .where(Device.first_seen_at >= sat_window)
        )
        or 0
    )
    saturated = recent_new >= settings.network_saturation_new_devices

    reasons = _build_reasons(
        total=total,
        last_scan_at=last_scan_at,
        now=now,
        down=down,
        down_gateways=down_gateways,
        new_last_window=new_last_window,
        crit_vuln_devices=crit_vuln_devices,
        high_vuln_devices=high_vuln_devices,
        med_vuln_devices=med_vuln_devices,
        arp_events=arp_events,
        outbound_events=outbound_events,
        portscan_events=portscan_events,
        new_port_events=new_port_events,
        saturated=saturated,
        recent_new=recent_new,
    )
    state = max(reasons, key=lambda r: _STATE_RANK[r.state]).state if reasons else "sain"

    return NetworkSummary(
        state=state,
        reasons=reasons,
        total=total,
        up=up,
        down=down,
        gateways=gateways,
        new_last_window=new_last_window,
        by_type=by_type,
        last_scan_at=last_scan_at,
        events_recent=events_recent,
    )


async def _count_devices_with_severity(db: AsyncSession, severity: str) -> int:
    return (
        await db.scalar(
            select(func.count(func.distinct(DeviceVuln.device_id))).where(
                DeviceVuln.severity == severity
            )
        )
        or 0
    )


def _build_reasons(
    *,
    total: int,
    last_scan_at: datetime | None,
    now: datetime,
    down: int,
    down_gateways: int,
    new_last_window: int,
    crit_vuln_devices: int,
    high_vuln_devices: int,
    med_vuln_devices: int,
    arp_events: int = 0,
    outbound_events: int = 0,
    portscan_events: int = 0,
    new_port_events: int = 0,
    saturated: bool = False,
    recent_new: int = 0,
) -> list[NetworkStateReason]:
    """Construit la liste des raisons d'état.

    Phase A : connectivité + fraîcheur. Phase B : vulnérabilités (critique →
    critique, élevée → alarme, moyenne → surveille). Phase C : intrusions
    (ARP spoof / flux sortants → critique, scan de ports → alarme, nouveaux
    ports → surveille) et saturation du parc.
    """
    # Angle mort : aucun appareil connu, ou scan trop ancien.
    stale_cutoff = now - timedelta(minutes=settings.network_scan_stale_minutes)
    if total == 0 or last_scan_at is None or last_scan_at < stale_cutoff:
        return [
            NetworkStateReason(
                state="indisponible",
                label="Aucun scan réseau récent",
                count=max(total, 0),
            )
        ]

    reasons: list[NetworkStateReason] = []
    if down_gateways > 0:
        reasons.append(
            NetworkStateReason(
                state="critique", label="Passerelle hors-ligne", count=down_gateways
            )
        )
    if crit_vuln_devices > 0:
        reasons.append(
            NetworkStateReason(
                state="critique",
                label="Vulnérabilités critiques",
                count=crit_vuln_devices,
            )
        )
    down_hosts = down - down_gateways
    if down_hosts > 0:
        reasons.append(
            NetworkStateReason(
                state="alarme", label="Appareils hors-ligne", count=down_hosts
            )
        )
    if high_vuln_devices > 0:
        reasons.append(
            NetworkStateReason(
                state="alarme",
                label="Vulnérabilités élevées",
                count=high_vuln_devices,
            )
        )
    if med_vuln_devices > 0:
        reasons.append(
            NetworkStateReason(
                state="surveille",
                label="Vulnérabilités moyennes",
                count=med_vuln_devices,
            )
        )
    # Intrusions (Phase C)
    if arp_events > 0:
        reasons.append(
            NetworkStateReason(
                state="critique", label="ARP spoofing détecté", count=arp_events
            )
        )
    if outbound_events > 0:
        reasons.append(
            NetworkStateReason(
                state="critique", label="Flux sortants suspects", count=outbound_events
            )
        )
    if portscan_events > 0:
        reasons.append(
            NetworkStateReason(
                state="alarme", label="Scan de ports détecté", count=portscan_events
            )
        )
    if saturated:
        reasons.append(
            NetworkStateReason(
                state="sature",
                label="Croissance anormale du parc",
                count=recent_new,
            )
        )
    if new_port_events > 0:
        reasons.append(
            NetworkStateReason(
                state="surveille",
                label="Nouveaux ports ouverts",
                count=new_port_events,
            )
        )
    if new_last_window > 0:
        reasons.append(
            NetworkStateReason(
                state="surveille",
                label="Nouveaux appareils détectés",
                count=new_last_window,
            )
        )
    return reasons
