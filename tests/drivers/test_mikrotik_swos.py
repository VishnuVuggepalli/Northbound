"""MikroTik SwOS driver tests — .b parser + read-only driver over fixtures.

Fixtures (tests/fixtures/mikrotik_swos/sys.b, link.b) are REAL responses captured
from a live CSS326-24G-2S+ on SwOS 2.18.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from northbound.drivers.base import NotSupported
from northbound.drivers.mikrotik_swos import (
    MikrotikSwosDriver,
    _hex_ascii,
    _hex_mac,
    _le_ip,
    _parse_swos,
    _uptime,
)
from northbound.schemas.driver import ConnectionParams, Credentials, PortChange

_DIR = Path(__file__).parent.parent / "fixtures" / "mikrotik_swos"


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, url: str, **_: Any) -> httpx.Response:
        self.calls.append(url)
        path = _DIR / url.lstrip("/")
        return httpx.Response(200, text=path.read_text() if path.exists() else "{}")

    async def aclose(self) -> None:
        return None


def _driver() -> tuple[MikrotikSwosDriver, _FakeClient]:
    fake = _FakeClient()
    drv = MikrotikSwosDriver(
        ConnectionParams(host="127.0.0.1"), Credentials(username="admin", password="x"), http=fake
    )
    return drv, fake


# --------------------------------------------------------------------------- #
# parser + decoders
# --------------------------------------------------------------------------- #
def test_parse_swos_scalars_and_arrays() -> None:
    d = _parse_swos("{a:0x1a,b:'4353',c:[0x07,0x02],d:'2cc81b46f40c'}")
    assert d["a"] == 26
    assert d["b"] == "4353"  # quoted stays raw hex
    assert d["c"] == [7, 2]
    assert d["d"] == "2cc81b46f40c"


def test_decoders() -> None:
    assert _hex_ascii("4353533332362d3234472d32532b") == "CSS326-24G-2S+"
    assert _hex_ascii("322e3138") == "2.18"
    assert _hex_mac("2cc81b46f40c") == "2c:c8:1b:46:f4:0c"
    assert _le_ip(0x6B58A8C0) == "192.168.88.107"  # little-endian
    assert _uptime(0) == "0d 0h 0m"


# --------------------------------------------------------------------------- #
# driver (against the real captured fixtures)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_test_credentials_reports_board_and_version() -> None:
    drv, _ = _driver()
    r = await drv.test_credentials()
    assert r.ok is True
    assert r.platform_version == "CSS326-24G-2S+ SwOS 2.18"


@pytest.mark.asyncio
async def test_system_info_facts() -> None:
    drv, _ = _driver()
    f = (await drv.get_system_info()).facts
    assert f.model == "CSS326-24G-2S+"
    assert f.os_version == "SwOS 2.18"
    assert f.serial == "HGW07D2VG5V"
    assert f.base_mac == "2c:c8:1b:46:f4:0c"


@pytest.mark.asyncio
async def test_get_ports_count_names_and_link_state() -> None:
    drv, _ = _driver()
    ports = await drv.get_ports()
    assert len(ports) == 26  # 24G + 2 SFP+
    by_name = {p.name: p for p in ports}
    # Names come from the device's nm[] (user labels).
    assert "Port1-Ian-BMC-16" in by_name
    assert "SFP1" in by_name
    # lnk mask 0x01202008 → ports 4,14,22,25 up; all enabled (en=0x03ffffff).
    up = {p.name for p in ports if p.link_up}
    assert up == {"Port4-240", "Port14-16", "Port22-16", "SFP1"}
    assert all(p.admin_up for p in ports)
    # linked ports decode a speed + full duplex; down ports report none.
    # SwOS spd is a table INDEX: code 2 → 1G (verified against the SwOS JS +
    # the SFP-GE-T 1000BASE-T module on SFP1).
    assert by_name["Port4-240"].speed_mbps == 1000
    assert by_name["SFP1"].speed_mbps == 1000
    assert by_name["Port4-240"].duplex == "full"
    assert by_name["Port1-Ian-BMC-16"].speed_mbps is None


@pytest.mark.asyncio
async def test_get_ports_vlans_from_fwd_and_vlan_b() -> None:
    """untagged = fwd.b dvid (matches the per-port access VLAN in the name);
    tagged = vlan.b members minus the default. Real CSS326 fixtures."""
    drv, _ = _driver()
    ports = await drv.get_ports()
    by_name = {p.name: p for p in ports}
    # dvid → untagged, validated against the VLAN encoded in the port name.
    assert by_name["Port1-Ian-BMC-16"].untagged_vlan == 16
    assert by_name["Port2-Roh-240"].untagged_vlan == 240
    assert by_name["Port3-116"].untagged_vlan == 116
    # tagged = member VLANs minus the port's own untagged; the device trunks 83
    # VLANs to every port, so each port is tagged on many — but never its own.
    p1 = by_name["Port1-Ian-BMC-16"]
    assert p1.untagged_vlan not in p1.tagged_vlans
    assert len(p1.tagged_vlans) > 1
    assert tuple(sorted(p1.tagged_vlans)) == p1.tagged_vlans  # sorted, deterministic


@pytest.mark.asyncio
async def test_get_vlans_lists_device_database() -> None:
    drv, _ = _driver()
    vlans = await drv.get_vlans()
    assert len(vlans) == 85  # vlan.b table size on the live device
    v1 = next(v for v in vlans if v.vlan_id == 1)
    assert v1.name == "VLAN-1" and v1.port_count == 26  # mbr 0x03ffffff = all ports


@pytest.mark.asyncio
async def test_l3_management_ip() -> None:
    drv, _ = _driver()
    l3 = await drv.get_l3_interfaces()
    assert len(l3) == 1
    assert l3[0].name == "management" and l3[0].ipv4 == "192.168.88.107"


@pytest.mark.asyncio
async def test_read_only_and_no_neighbors() -> None:
    drv, _ = _driver()
    assert MikrotikSwosDriver.capabilities.writable is False
    assert await drv.get_neighbors() == []
    with pytest.raises(NotSupported):
        await drv.render_change("Port1", PortChange(description="x"))
