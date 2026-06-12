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


# --------------------------------------------------------------------------- #
# host (MAC) table + Diagnostics counters — captured live from the CSS326
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_system_info_mac_table_from_dhost() -> None:
    """get_system_info reads /!dhost.b: adr→MAC, vid→VLAN, prt→0-based port
    index resolved to its link.b name (the learned MACs are on the SFP uplink)."""
    drv, fake = _driver()
    info = await drv.get_system_info()
    assert info.mac_supported is True
    assert len(info.mac_table) == 5
    first = info.mac_table[0]
    assert first.mac == "04:f4:1c:57:3b:d7"
    assert first.vlan == 117  # vid 0x0075
    assert first.interface == "SFP1"  # prt 0x18 = index 24 → link.b nm[24]
    assert first.type == "Dynamic"
    assert "/!dhost.b" in fake.calls


@pytest.mark.asyncio
async def test_get_system_info_mac_unsupported_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host-table read failure degrades to mac_supported=False without sinking
    the rest of the snapshot (facts still resolve)."""
    drv, _ = _driver()
    real = drv._get_array

    async def _flaky(endpoint: str) -> Any:
        if endpoint == "!dhost.b":
            from northbound.drivers.base import DriverError

            raise DriverError("host table truncated")
        return await real(endpoint)

    monkeypatch.setattr(drv, "_get_array", _flaky)
    info = await drv.get_system_info()
    assert info.mac_supported is False
    assert info.mac_table == ()
    assert info.facts.model == "CSS326-24G-2S+"


@pytest.mark.asyncio
async def test_diagnostics_counters_and_histogram() -> None:
    """Diagnostics 'Counters' returns three tables from stats.b: traffic counters
    (64-bit bytes + rtp/ttp packets), errors, and the RMON packet-size histogram."""
    drv, _ = _driver()
    detail = await drv.get_protocol_detail("Counters")
    assert detail.error is None
    titles = [t.title for t in detail.tables]
    assert titles == ["Port counters", "Errors", "Packet-size histogram"]

    counters = detail.tables[0]
    assert counters.columns == ("Port", "RX", "TX", "RX pkts", "TX pkts")
    assert len(counters.rows) == 26  # one row per port
    # RX bytes are humanized (64-bit low/high combined), packets are integers
    rx = counters.rows[1][1]
    assert rx[-1] in {"B", "KB", "MB", "GB", "TB"} or rx.endswith("B")

    errors = detail.tables[1]
    assert errors.columns[0] == "Port" and "RX FCS" in errors.columns
    assert len(errors.rows) == 26

    hist = detail.tables[2]
    assert hist.columns == ("Port", "64", "65-127", "128-255", "256-511", "512-1023", "1024+")
    assert len(hist.rows) == 26


@pytest.mark.asyncio
async def test_diagnostics_non_counter_slug_empty() -> None:
    """SwOS is L2-only: Routing/ARP/Optics slugs return empty (no such tables)."""
    drv, _ = _driver()
    for slug in ("Routing", "ARP", "Optics"):
        detail = await drv.get_protocol_detail(slug)
        assert detail.tables == ()
        assert detail.error is None
