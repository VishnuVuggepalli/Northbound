"""CiscoDriver (NAPALM-backed) — parser units + write-path via a fake NAPALM
device. No live network: a fake `napalm` device is injected through `device=`."""

from __future__ import annotations

from typing import Any

import pytest

from northbound.drivers.cisco import (
    CiscoDriver,
    _build_change_commands,
    _merge_ports,
    _parse_lldp_detail,
    _parse_switchport_text,
    _parse_vlan_list,
)
from northbound.schemas.driver import ConnectionParams, Credentials, PortChange

# --------------------------------------------------------------------------- #
# Pure parsers
# --------------------------------------------------------------------------- #
_IOS_STATUS = """
Port      Name               Status       Vlan       Duplex  Speed Type
Gi0/0                        connected    routed     a-full   auto RJ45
Gi0/1                        connected    20         a-full   auto RJ45
Gi0/2                        disabled     1          auto     auto RJ45
"""

_NXOS_SWITCHPORT = """
Name: Ethernet1/1
  Switchport: Enabled
  Operational Mode: access
  Access Mode VLAN: 30 (VLAN0030)
  Trunking Native Mode VLAN: 1 (default)
  Trunking VLANs Allowed: 1-4094

Name: Ethernet1/2
  Switchport: Enabled
  Operational Mode: trunk
  Access Mode VLAN: 1 (default)
  Trunking Native Mode VLAN: 99 (VLAN0099)
  Trunking VLANs Allowed: 10,20,30
"""


def test_parse_switchport_text_ios_status() -> None:
    sw = _parse_switchport_text("cisco_ios", "show interfaces status", _IOS_STATUS)
    assert sw["Gi0/1"][0] == 20  # access VLAN
    assert sw["Gi0/0"][0] is None  # routed → not a VLAN
    assert sw["Gi0/2"][0] == 1


def test_parse_switchport_text_nxos() -> None:
    sw = _parse_switchport_text("cisco_nxos", "show interface switchport", _NXOS_SWITCHPORT)
    assert sw["Ethernet1/1"] == (30, ())  # access
    untagged, tagged = sw["Ethernet1/2"]  # trunk
    assert untagged == 99 and tagged == (10, 20, 30)


def test_parse_switchport_text_empty() -> None:
    assert _parse_switchport_text("cisco_ios", "show interfaces status", "") == {}


def test_parse_switchport_text_logs_on_parse_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A parse failure must log (not silently blank the VLAN columns)."""
    import ntc_templates.parse as ntc

    def _boom(**_kw: object) -> object:
        raise ValueError("template engine blew up")

    monkeypatch.setattr(ntc, "parse_output", _boom)
    with caplog.at_level("WARNING", logger="northbound.drivers.cisco"):
        out = _parse_switchport_text("cisco_ios", "show interfaces status", "Gi0/1 connected 20")
    assert out == {}  # still degrades gracefully
    assert any("switchport parse failed" in r.message for r in caplog.records)


def test_parse_vlan_list_ranges_and_sentinels() -> None:
    assert _parse_vlan_list("10,20,30-32") == (10, 20, 30, 31, 32)
    assert _parse_vlan_list("1-4094") == ()
    assert _parse_vlan_list("ALL") == ()
    assert _parse_vlan_list([10, 20]) == (10, 20)


def test_merge_ports_applies_vlans() -> None:
    interfaces = {
        "Ethernet1/1": {"is_enabled": True, "is_up": True, "description": "x", "mtu": 1500},
    }
    ports = {p.name: p for p in _merge_ports(interfaces, {"Ethernet1/1": (30, ())})}
    assert ports["Ethernet1/1"].untagged_vlan == 30 and ports["Ethernet1/1"].admin_up is True


def test_parse_lldp_detail_prefix() -> None:
    detail = {
        "Ethernet1/1": [
            {
                "remote_chassis_id": "5254.00aa.bb01",
                "remote_port": "Ethernet1/9",
                "remote_system_name": "peer",
                "remote_system_description": "NX-OS",
            }
        ]
    }
    n = _parse_lldp_detail(detail)[0]
    assert n.port_id == "Ethernet1/9" and n.system_name == "peer"
    assert n.system_description is not None and n.system_description.startswith("[Ethernet1/1] ")


def test_build_change_commands_nxos_bare_switchport_before_mode() -> None:
    cmds = _build_change_commands("Ethernet1/1", PortChange(untagged_vlan=20))
    # bare 'switchport' must precede 'switchport mode access' (NX-OS L3 default)
    assert cmds.index("  switchport") < cmds.index("  switchport mode access")
    assert "  switchport access vlan 20" in cmds


def test_build_change_commands_trunk_replace() -> None:
    cmds = _build_change_commands(
        "Ethernet1/1", PortChange(untagged_vlan=100, tagged_vlans=[10, 20])
    )
    assert "  switchport mode trunk" in cmds
    assert "  switchport trunk native vlan 100" in cmds
    assert "  switchport trunk allowed vlan 10,20" in cmds


# --------------------------------------------------------------------------- #
# Driver via injected fake NAPALM device
# --------------------------------------------------------------------------- #
class _FakeCiscoNapalm:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def open(self) -> None: ...
    def close(self) -> None: ...
    def is_alive(self) -> dict[str, bool]:
        return {"is_alive": True}

    def get_facts(self) -> dict[str, str]:
        return {"model": "N9K-v", "os_version": "9.3", "hostname": "nx1"}

    def get_config(self, retrieve: str = "all") -> dict[str, str]:
        return {"running": "! running\n", "candidate": "", "startup": ""}

    def get_interfaces(self) -> dict[str, Any]:
        return {"Ethernet1/1": {"is_enabled": True, "is_up": True, "description": "", "mtu": 1500}}

    def get_lldp_neighbors_detail(self) -> dict[str, Any]:
        return {}

    def cli(self, cmds: list[str]) -> dict[str, str]:
        return {cmds[0]: _NXOS_SWITCHPORT}

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


def _driver(fake: _FakeCiscoNapalm) -> CiscoDriver:
    return CiscoDriver(
        ConnectionParams(host="127.0.0.1", prefer_native_api=True),
        Credentials(username="admin", password="pw"),
        device=fake,
    )


@pytest.mark.asyncio
async def test_get_ports_reads_switchport_vlans() -> None:
    d = _driver(_FakeCiscoNapalm())
    ports = {p.name: p for p in await d.get_ports()}
    assert ports["Ethernet1/1"].untagged_vlan == 30  # from fake cli switchport


@pytest.mark.asyncio
async def test_apply_confirmed_commit_then_confirm() -> None:
    fake = _FakeCiscoNapalm()
    d = _driver(fake)
    diff = await d.render_change("Ethernet1/1", PortChange(untagged_vlan=20))
    res = await d.apply_change(diff, confirm_seconds=30)
    assert res.success is True and res.confirm_token is not None
    assert ("commit_config", 30) in fake.calls
    await d.confirm(res.confirm_token)
    assert ("confirm_commit", None) in fake.calls
    await d.revert(res.confirm_token)
    assert ("rollback", None) in fake.calls


@pytest.mark.asyncio
async def test_apply_failure_discards_candidate() -> None:
    fake = _FakeCiscoNapalm()

    def boom(message: str = "", revert_in: int | None = None) -> None:
        raise RuntimeError("CLI command failed: invalid command")

    fake.commit_config = boom  # type: ignore[method-assign]
    d = _driver(fake)
    diff = await d.render_change("Ethernet1/1", PortChange(untagged_vlan=20))
    res = await d.apply_change(diff)
    assert res.success is False and res.error and "invalid command" in res.error
    assert ("discard_config", None) in fake.calls


def _drv(nxos: bool) -> CiscoDriver:
    d = CiscoDriver.__new__(CiscoDriver)
    d._use_native = nxos  # nxos vs ios template selection
    return d


@pytest.mark.asyncio
async def test_cisco_ios_vs_nxos_svi_vrf() -> None:
    from northbound.schemas.driver import L3Change

    ch = L3Change(action="create", kind="svi", vlan_id=10, ipv4="10.0.0.1/24", vrf="Red")
    ios = (await _drv(False).render_l3_change(ch)).commands
    nx = (await _drv(True).render_l3_change(ch)).commands
    # IOS: dotted mask + `vrf forwarding`; NX-OS: CIDR + `vrf member` + feature.
    assert " ip address 10.0.0.1 255.255.255.0" in ios and " vrf forwarding Red" in ios
    assert "  ip address 10.0.0.1/24" in nx and "  vrf member Red" in nx
    assert "feature interface-vlan" in nx
    # vrf binding precedes the address on both (device clears L3 on vrf change)
    assert nx.index("  vrf member Red") < nx.index("  ip address 10.0.0.1/24")


@pytest.mark.asyncio
async def test_cisco_ios_vs_nxos_vrf_object() -> None:
    from northbound.schemas.driver import VrfChange

    ch = VrfChange(action="create", name="Red")
    assert "vrf definition Red" in (await _drv(False).render_vrf_change(ch)).commands
    assert "vrf context Red" in (await _drv(True).render_vrf_change(ch)).commands


@pytest.mark.asyncio
async def test_cisco_ios_vs_nxos_ospf_interface() -> None:
    from northbound.schemas.driver import OspfChange

    ch = OspfChange(action="set", target="interface", interface="Vlan10", area="0", cost=5)
    ios = (await _drv(False).render_ospf_change(ch)).commands
    nx = (await _drv(True).render_ospf_change(ch)).commands
    assert " ip ospf 1 area 0" in ios  # IOS
    assert "  ip router ospf 1 area 0" in nx and "feature ospf" in nx  # NX-OS
