"""Tests de l'enrichissement SNMP : sync des interfaces (DB mockée)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.models.device import Device
from app.models.device_interface import DeviceInterface
from app.schemas.network import ScanDevice, ScanInterface
from app.services import network


def _device(id_: int = 7) -> Device:
    d = Device(discovered_by_machine_id=1, ip="192.168.1.10")
    d.id = id_
    return d


@pytest.mark.asyncio
async def test_sync_interfaces_inserts_maps_and_dedups() -> None:
    db = AsyncMock()
    added: list[DeviceInterface] = []
    db.add = lambda obj: added.append(obj)  # add est synchrone côté SQLAlchemy
    db.execute = AsyncMock()

    sd = ScanDevice(
        ip="192.168.1.10",
        snmp_reachable=True,
        interfaces=[
            ScanInterface(
                if_index=1,
                name="eth0",
                mac="AA:BB:CC:DD:EE:FF",
                admin_up=True,
                oper_up=True,
                speed_bps=1_000_000_000,
                mtu=1500,
                in_octets=123,
                out_octets=456,
            ),
            ScanInterface(if_index=2, name="eth1", oper_up=False),
            ScanInterface(if_index=1, name="doublon"),  # même ifIndex → ignoré
        ],
    )
    now = datetime.now(timezone.utc)

    await network._sync_interfaces(db, _device(7), sd, now)

    # Un delete préalable (recompute) puis 2 interfaces (le doublon est filtré).
    db.execute.assert_awaited()
    assert len(added) == 2
    assert {i.if_index for i in added} == {1, 2}

    eth0 = next(i for i in added if i.if_index == 1)
    assert eth0.name == "eth0"
    assert eth0.device_id == 7
    assert eth0.mac == "AA:BB:CC:DD:EE:FF"
    assert eth0.oper_up is True
    assert eth0.speed_bps == 1_000_000_000
    assert eth0.in_octets == 123
    assert eth0.last_seen_at == now


def test_scan_device_defaults_without_snmp() -> None:
    # Un appareil sans SNMP garde des valeurs par défaut sûres.
    sd = ScanDevice(ip="10.0.0.5")
    assert sd.snmp_reachable is False
    assert sd.interfaces == []
    assert sd.sys_uptime_secs is None
