"""MikroTik RouterOS driver tests — REST parsing + write-path rendering.

The RouterOS REST transport is faked: GET /rest/<menu> serves the matching
fixture (all-string values, as the real API returns); PATCH/POST echo 200 and
record the call so write assertions can inspect what would hit the device.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from northbound.drivers.base import DriverError, NotSupported
from northbound.drivers.mikrotik import (
    MikrotikDriver,
    _parse_vlan_ids,
    _speed_mbps,
)
from northbound.schemas.driver import ConnectionParams, Credentials, PortChange

_DIR = Path(__file__).parent.parent / "fixtures" / "mikrotik"


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def _load(self, menu: str) -> Any:
        path = _DIR / (menu.replace("/", "_") + ".json")
        return json.loads(path.read_text()) if path.exists() else []

    async def get(self, url: str, *, headers: Any = None, params: Any = None) -> httpx.Response:
        self.calls.append(("GET", url))
        return httpx.Response(200, json=self._load(url.removeprefix("/rest/")))

    async def request(
        self, method: str, url: str, *, headers: Any = None, json: Any = None, params: Any = None
    ) -> httpx.Response:
        self.calls.append((method, url, str(json)))
        if url == "/rest/export":
            return httpx.Response(200, json=[{"ret": "# config\n"}])
        return httpx.Response(200, json=json or {})

    async def aclose(self) -> None:
        return None


def _driver() -> tuple[MikrotikDriver, _FakeClient]:
    fake = _FakeClient()
    drv = MikrotikDriver(
        ConnectionParams(host="127.0.0.1"), Credentials(username="admin", password="pw"), http=fake
    )
    return drv, fake


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_speed_mbps() -> None:
    assert _speed_mbps("1Gbps") == 1000
    assert _speed_mbps("10Gbps") == 10000
    assert _speed_mbps("100Mbps") == 100
    assert _speed_mbps("") is None


def test_parse_vlan_ids() -> None:
    assert _parse_vlan_ids("10") == [10]
    assert _parse_vlan_ids("10-12") == [10, 11, 12]
    assert _parse_vlan_ids("10,20-21") == [10, 20, 21]
    assert _parse_vlan_ids("") == []


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_ports_parses_state_speed_and_vlans() -> None:
    drv, _ = _driver()
    ports = {p.name: p for p in await drv.get_ports()}
    assert ports["ether1"].admin_up is True  # disabled=false
    assert ports["ether2"].admin_up is False  # disabled=true
    assert ports["ether1"].link_up is True  # running=true
    assert ports["ether1"].speed_mbps == 1000
    assert ports["ether1"].description == "uplink"  # comment → description
    # ether1 is a tagged member of vlan-ids 200,300; pvid 100 is its access VLAN
    assert ports["ether1"].untagged_vlan == 100
    assert ports["ether1"].tagged_vlans == (200, 300)


@pytest.mark.asyncio
async def test_get_vlans() -> None:
    drv, _ = _driver()
    vlans = {v.vlan_id for v in await drv.get_vlans()}
    assert {100, 200, 300} <= vlans


@pytest.mark.asyncio
async def test_get_l3_interfaces() -> None:
    drv, _ = _driver()
    l3 = {i.name: i for i in await drv.get_l3_interfaces()}
    assert l3["bridge1"].ipv4 == "192.168.88.1/24"
    assert l3["vlan100"].kind == "svi"  # type vlan → svi


@pytest.mark.asyncio
async def test_get_neighbors() -> None:
    drv, _ = _driver()
    neighbors = await drv.get_neighbors()
    assert len(neighbors) == 1
    assert neighbors[0].system_name == "neighbor-sw"


@pytest.mark.asyncio
async def test_test_credentials_reports_version() -> None:
    drv, _ = _driver()
    result = await drv.test_credentials()
    assert result.ok is True
    assert "7.14.2" in (result.platform_version or "")


# --------------------------------------------------------------------------- #
# writes
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_render_and_apply_description_and_enable() -> None:
    drv, fake = _driver()
    diff = await drv.render_change("ether1", PortChange(description="srv-7", enabled=False))
    result = await drv.apply_change(diff)
    assert result.success is True
    assert result.confirm_token is None  # RouterOS commits immediately
    patches = [c for c in fake.calls if c[0] == "PATCH"]
    assert any("/rest/interface/*1" in c[1] and "srv-7" in c[2] for c in patches)
    assert any("disabled" in c[2] and "true" in c[2] for c in patches)


@pytest.mark.asyncio
async def test_render_access_vlan_sets_bridge_pvid() -> None:
    drv, fake = _driver()
    diff = await drv.render_change("ether1", PortChange(untagged_vlan=250))
    await drv.apply_change(diff)
    # access VLAN is written as the bridge port's pvid (id *10 for ether1)
    assert any(
        c[0] == "PATCH" and "/rest/interface/bridge/port/*10" in c[1] and "250" in c[2]
        for c in fake.calls
    )


@pytest.mark.asyncio
async def test_render_trunk_change_not_supported() -> None:
    drv, _ = _driver()
    with pytest.raises(NotSupported):
        await drv.render_change("ether1", PortChange(port_mode="trunk", tagged_vlans=[10, 20]))


@pytest.mark.asyncio
async def test_render_unknown_port_raises() -> None:
    drv, _ = _driver()
    with pytest.raises(DriverError):
        await drv.render_change("nonexistent99", PortChange(description="x"))
