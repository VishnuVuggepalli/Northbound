"""AristaDriver (NAPALM-backed) — parser units + write-path via a fake NAPALM
device. No live network: a fake `napalm` device is injected through the
driver's `device=` hook, exercising the same code paths NAPALM's eos driver
would drive."""

from __future__ import annotations

from typing import Any

import pytest

from northbound.drivers.arista import (
    AristaDriver,
    _merge_ports,
    _parse_allowed,
    _parse_lldp_detail,
    _vlans_for,
)
from northbound.schemas.driver import ConnectionParams, Credentials, PortChange, PortState


# --------------------------------------------------------------------------- #
# Pure parsers
# --------------------------------------------------------------------------- #
def test_vlans_for_access_and_trunk() -> None:
    acc = {"switchportInfo": {"mode": "access", "accessVlanId": 20}}
    assert _vlans_for(acc) == (20, ())
    trk = {
        "switchportInfo": {
            "mode": "trunk",
            "trunkingNativeVlanId": 100,
            "trunkAllowedVlans": "100,200,300",
        }
    }
    assert _vlans_for(trk) == (100, (100, 200, 300))
    assert _vlans_for(None) == (None, ())
    assert _vlans_for({"switchportInfo": {"mode": "routed"}}) == (None, ())


def test_parse_allowed_ranges_and_sentinels() -> None:
    assert _parse_allowed("10,20,30-32") == (10, 20, 30, 31, 32)
    assert _parse_allowed("ALL") == ()
    assert _parse_allowed("1-4094") == ()
    assert _parse_allowed("") == ()


def test_merge_ports_maps_interfaces_and_switchport_vlans() -> None:
    interfaces = {
        "Ethernet1": {
            "is_enabled": True,
            "is_up": True,
            "description": "to-host",
            "speed": 10000,
            "mac_address": "00:1c:73:aa:bb:01",
            "mtu": 9214,
        },
        "Ethernet2": {"is_enabled": False, "is_up": False, "description": ""},
    }
    switchports = {
        "Ethernet1": {"switchportInfo": {"mode": "access", "accessVlanId": 20}},
        "Ethernet2": {
            "switchportInfo": {
                "mode": "trunk",
                "trunkingNativeVlanId": 1,
                "trunkAllowedVlans": "10,20",
            }
        },
    }
    ports = {p.name: p for p in _merge_ports(interfaces, switchports)}
    assert isinstance(ports["Ethernet1"], PortState)
    assert ports["Ethernet1"].untagged_vlan == 20 and ports["Ethernet1"].tagged_vlans == ()
    assert ports["Ethernet1"].admin_up is True and ports["Ethernet1"].speed_mbps == 10000
    assert ports["Ethernet2"].admin_up is False
    assert ports["Ethernet2"].untagged_vlan == 1 and ports["Ethernet2"].tagged_vlans == (10, 20)


def test_parse_lldp_detail_encodes_local_port_prefix() -> None:
    detail = {
        "Ethernet1": [
            {
                "remote_chassis_id": "aa:bb:cc:dd:ee:01",
                "remote_port": "Ethernet9",
                "remote_system_name": "peer-01",
                "remote_system_description": "Arista EOS",
            }
        ]
    }
    nbrs = _parse_lldp_detail(detail)
    assert len(nbrs) == 1
    assert nbrs[0].chassis_id == "aa:bb:cc:dd:ee:01"
    assert nbrs[0].port_id == "Ethernet9"
    assert nbrs[0].system_name == "peer-01"
    assert nbrs[0].system_description is not None
    assert nbrs[0].system_description.startswith("[Ethernet1] ")


# --------------------------------------------------------------------------- #
# Driver via injected fake NAPALM device
# --------------------------------------------------------------------------- #
class _FakeNode:
    """pyeapi node stand-in — only run_commands(show interfaces switchport)."""

    def __init__(self, switchports: dict[str, Any]) -> None:
        self._sw = switchports

    def run_commands(self, cmds: list[str], encoding: str = "json") -> list[dict[str, Any]]:
        return [{"switchports": self._sw}]


class _FakeNapalm:
    """Implements the slice of NAPALM's eos driver the AristaDriver calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.device = _FakeNode(
            {"Ethernet1": {"switchportInfo": {"mode": "access", "accessVlanId": 10}}}
        )

    def open(self) -> None:
        self.calls.append(("open", None))

    def close(self) -> None:
        self.calls.append(("close", None))

    def is_alive(self) -> dict[str, bool]:
        return {"is_alive": True}

    def get_facts(self) -> dict[str, str]:
        return {"vendor": "Arista", "model": "vEOS", "os_version": "4.27.0F", "hostname": "leaf1"}

    def get_config(self, retrieve: str = "all") -> dict[str, str]:
        return {"running": "! running\nhostname leaf1\n", "candidate": "", "startup": ""}

    def get_interfaces(self) -> dict[str, Any]:
        return {"Ethernet1": {"is_enabled": True, "is_up": True, "description": "", "mtu": 1500}}

    def get_lldp_neighbors_detail(self) -> dict[str, Any]:
        return {}

    def load_merge_candidate(self, config: str | None = None) -> None:
        self.calls.append(("load_merge_candidate", config))

    def commit_config(self, message: str = "", revert_in: int | None = None) -> None:
        self.calls.append(("commit_config", revert_in))

    def confirm_commit(self) -> None:
        self.calls.append(("confirm_commit", None))

    def rollback(self) -> None:
        self.calls.append(("rollback", None))

    def discard_config(self) -> None:
        self.calls.append(("discard_config", None))


def _driver(fake: _FakeNapalm) -> AristaDriver:
    return AristaDriver(
        ConnectionParams(host="127.0.0.1"),
        Credentials(username="admin", password="pw"),
        device=fake,
    )


@pytest.mark.asyncio
async def test_test_credentials_uses_get_facts() -> None:
    d = _driver(_FakeNapalm())
    tr = await d.test_credentials()
    assert tr.ok is True
    assert tr.platform_version is not None and "4.27.0F" in tr.platform_version


@pytest.mark.asyncio
async def test_get_ports_merges_interfaces_and_switchport() -> None:
    d = _driver(_FakeNapalm())
    ports = {p.name: p for p in await d.get_ports()}
    assert ports["Ethernet1"].untagged_vlan == 10  # from fake switchport


@pytest.mark.asyncio
async def test_apply_uses_confirmed_commit_then_confirm() -> None:
    fake = _FakeNapalm()
    d = _driver(fake)
    diff = await d.render_change("Ethernet1", PortChange(untagged_vlan=20))
    res = await d.apply_change(diff, confirm_seconds=45)
    assert res.success is True and res.confirm_deadline_at is not None
    assert res.confirm_token is not None
    # NAPALM confirmed-commit: load candidate, then commit with revert timer.
    assert ("load_merge_candidate", "\n".join(diff.commands)) in fake.calls
    assert ("commit_config", 45) in fake.calls
    await d.confirm(res.confirm_token)
    assert ("confirm_commit", None) in fake.calls


@pytest.mark.asyncio
async def test_revert_calls_rollback() -> None:
    fake = _FakeNapalm()
    d = _driver(fake)
    await d.revert("nb-x")
    assert ("rollback", None) in fake.calls


@pytest.mark.asyncio
async def test_apply_failure_discards_candidate() -> None:
    fake = _FakeNapalm()

    def boom(message: str = "", revert_in: int | None = None) -> None:
        raise RuntimeError("commit failed: invalid command")

    fake.commit_config = boom  # type: ignore[method-assign]
    d = _driver(fake)
    diff = await d.render_change("Ethernet1", PortChange(untagged_vlan=20))
    res = await d.apply_change(diff)
    assert res.success is False and res.error and "commit failed" in res.error
    # candidate cleared on failure so the session isn't left dirty
    assert ("discard_config", None) in fake.calls


@pytest.mark.asyncio
async def test_render_change_trunk_commands() -> None:
    d = _driver(_FakeNapalm())
    diff = await d.render_change(
        "Ethernet9", PortChange(untagged_vlan=100, tagged_vlans=[100, 200])
    )
    body = "\n".join(diff.commands)
    assert "switchport mode trunk" in body
    assert "switchport trunk native vlan 100" in body
    assert "switchport trunk allowed vlan 100,200" in body
