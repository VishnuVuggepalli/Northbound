"""Pica8Driver — XML parser + write-path unit tests.

Transport is mocked via a fake ncclient manager. Parser tests work on the
canned XML fixtures under ``tests/fixtures/pica8/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lxml import etree  # type: ignore[attr-defined]  # lxml has no stubs; etree is C-extension

from northbound._lib.transport.netconf_client import NetconfClient, NetconfParams
from northbound.drivers.base import DriverError
from northbound.drivers.pica8 import (
    Pica8Driver,
    _build_edit_config_xml,
    _collapse_logical_units,
    _localname,
    _parse_interfaces_xml,
    _parse_lldp_xml,
    _parse_mac_table,
    _parse_protocols_xml,
    _parse_services_xml,
)
from northbound.schemas.driver import (
    ConfigDiff,
    ConnectionParams,
    Credentials,
    PortChange,
    PortState,
)

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "pica8"


def _load(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text()


# ---------------------------------------------------------------------------
# Parser tests — pure, no transport
# ---------------------------------------------------------------------------


def test_parse_interfaces_xml_returns_PortState_list() -> None:
    # Real PicOS xorplus schema: <gigabit-ethernet> entries (verified live vs
    # PicOS-V 4.2.2). Ports are te-1/1/x, fields name/description/mtu/disable.
    ports = _parse_interfaces_xml(_load("get_interfaces.xml"))
    assert len(ports) == 3
    by_name = {p.name: p for p in ports}
    assert isinstance(by_name["te-1/1/1"], PortState)
    assert by_name["te-1/1/1"].description == "uplink-to-core"
    assert by_name["te-1/1/1"].admin_up is True
    assert by_name["te-1/1/1"].mtu == 9216


def test_parse_interfaces_disabled_port_admin_down() -> None:
    # <disable>true</disable> is a boolean-VALUE leaf (not a Junos presence flag).
    ports = {p.name: p for p in _parse_interfaces_xml(_load("get_interfaces.xml"))}
    assert ports["te-1/1/2"].admin_up is False
    assert ports["te-1/1/3"].admin_up is True  # <disable>false</disable> ⇒ up


def test_parse_interfaces_no_vlan_model_yields_none() -> None:
    # This PicOS mode carries no per-port Junos VLAN membership in get-config;
    # ports parse with untagged_vlan=None / no tagged VLANs (not a crash).
    ports = {p.name: p for p in _parse_interfaces_xml(_load("get_interfaces.xml"))}
    assert ports["te-1/1/1"].untagged_vlan is None
    assert ports["te-1/1/1"].tagged_vlans == ()


def _port(name: str) -> PortState:
    return PortState(
        name=name,
        admin_up=True,
        link_up=True,
        speed_mbps=None,
        duplex=None,
        mac=None,
        mtu=1500,
        untagged_vlan=None,
        tagged_vlans=(),
        description="",
        host_model="",
        bmc_ip="",
        notes="",
        services={},
    )


def test_collapse_logical_units_drops_subunits_with_present_parent() -> None:
    # PicOS reports both physical xe-1/1/1 and its logical units xe-1/1/1.N.
    # For a switchport view we keep the physical and drop the units.
    ports = [_port("xe-1/1/1"), _port("xe-1/1/1.1"), _port("xe-1/1/1.4"), _port("xe-1/1/2")]
    names = {p.name for p in _collapse_logical_units(ports)}
    assert names == {"xe-1/1/1", "xe-1/1/2"}


def test_collapse_logical_units_keeps_orphan_units() -> None:
    # A unit whose physical parent is absent is kept — no data silently lost.
    ports = [_port("vlan.100"), _port("xe-1/1/9.2")]
    names = {p.name for p in _collapse_logical_units(ports)}
    assert names == {"vlan.100", "xe-1/1/9.2"}


def test_parse_lldp_xml_returns_neighbors() -> None:
    neighbors = _parse_lldp_xml(_load("get_lldp.xml"))
    assert len(neighbors) == 2
    by_local = {n.port_id: n for n in neighbors}
    assert "ge-1/1/1" in by_local
    assert by_local["ge-1/1/1"].chassis_id == "aa:bb:cc:dd:ee:01"
    assert by_local["ge-1/1/1"].system_name == "host-01"


def test_parse_lldp_invalid_xml_returns_empty() -> None:
    assert _parse_lldp_xml("not xml at all <<<") == []
    assert _parse_lldp_xml("") == []


def test_localname_strips_namespace() -> None:
    assert _localname("{http://xml.juniper.net/xnm/1.1/xnm}interface") == "interface"
    assert _localname("interface") == "interface"
    assert _localname(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# render_change — pure XML generation
# ---------------------------------------------------------------------------


def test_render_change_builds_edit_config_xml_access() -> None:
    xml = _build_edit_config_xml("ge-1/1/1", PortChange(description="srv-01", untagged_vlan=10))
    root = etree.fromstring(xml.encode())
    assert root.tag == "config"
    iface = root.find(".//interface")
    assert iface is not None
    assert iface.findtext("name") == "ge-1/1/1"
    assert iface.findtext("description") == "srv-01"
    # access mode + vlan 10
    eth_sw = root.find(".//ethernet-switching")
    assert eth_sw is not None
    assert eth_sw.findtext("port-mode") == "access"
    members = root.findall(".//members")
    assert [m.text for m in members] == ["10"]


def test_render_change_builds_edit_config_xml_trunk() -> None:
    xml = _build_edit_config_xml(
        "ge-1/1/3", PortChange(untagged_vlan=100, tagged_vlans=[100, 200, 300])
    )
    root = etree.fromstring(xml.encode())
    eth_sw = root.find(".//ethernet-switching")
    assert eth_sw is not None
    assert eth_sw.findtext("port-mode") == "trunk"
    assert eth_sw.findtext("native-vlan-id") == "100"
    members = root.findall(".//members")
    assert [m.text for m in members] == ["100", "200", "300"]


# ---------------------------------------------------------------------------
# Write-path tests — mock NetconfClient via ncclient manager_factory
# ---------------------------------------------------------------------------


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._running = _load("get_interfaces.xml")

    def get_config(self, source: str, filter: Any = None, with_defaults: Any = None) -> str:
        self.calls.append(("get_config", (source,)))
        return self._running

    def edit_config(
        self,
        config: str,
        format: str = "xml",
        target: str = "candidate",
        default_operation: str | None = None,
        test_option: str | None = None,
        error_option: str | None = None,
    ) -> str:
        # Signature mirrors REAL ncclient; record (target, config) for assertions.
        self.calls.append(("edit_config", (target, config)))
        return "<ok/>"

    def commit(
        self,
        confirmed: bool = False,
        timeout: int | None = None,
        persist: Any = None,
        persist_id: Any = None,
    ) -> str:
        self.calls.append(("commit", (confirmed, timeout)))
        return "<ok/>"

    def discard_changes(self) -> str:
        self.calls.append(("discard_changes", ()))
        return "<ok/>"

    def close_session(self) -> None:
        self.calls.append(("close_session", ()))


def _make_driver() -> tuple[Pica8Driver, _FakeManager]:
    fake = _FakeManager()
    netconf = NetconfClient(
        NetconfParams(host="pica8.test", username="u", password="p"),
        manager_factory=lambda: fake,
    )
    drv = Pica8Driver(
        ConnectionParams(host="127.0.0.1"),
        Credentials(username="u", password="p"),
        netconf=netconf,
    )
    return drv, fake


@pytest.mark.asyncio
async def test_apply_change_calls_commit_confirmed() -> None:
    drv, fake = _make_driver()
    diff = await drv.render_change("ge-1/1/1", PortChange(untagged_vlan=10))
    result = await drv.apply_change(diff, confirm_seconds=45)
    assert result.success is True
    # First write call is edit_config to candidate.
    edit_call = next(c for c in fake.calls if c[0] == "edit_config")
    target, payload = edit_call[1]
    assert target == "candidate"
    assert "<port-mode>access</port-mode>" in payload
    # Second write call is commit confirmed with the requested timeout.
    commit_call = next(c for c in fake.calls if c[0] == "commit")
    confirmed, timeout = commit_call[1]
    assert confirmed is True
    # ncclient needs the confirm-timeout as str (lxml text); wrapper coerces.
    assert timeout == "45"


@pytest.mark.asyncio
async def test_confirm_calls_commit_without_confirmed_flag() -> None:
    drv, fake = _make_driver()
    diff = await drv.render_change("ge-1/1/1", PortChange(untagged_vlan=10))
    apply_result = await drv.apply_change(diff)
    assert apply_result.confirm_token is not None
    fake.calls.clear()
    await drv.confirm(apply_result.confirm_token)
    commit_calls = [c for c in fake.calls if c[0] == "commit"]
    assert len(commit_calls) == 1
    confirmed, _timeout = commit_calls[0][1]
    assert confirmed is False


@pytest.mark.asyncio
async def test_revert_calls_discard_changes() -> None:
    drv, fake = _make_driver()
    diff = await drv.render_change("ge-1/1/1", PortChange(untagged_vlan=10))
    apply_result = await drv.apply_change(diff)
    assert apply_result.confirm_token is not None
    fake.calls.clear()
    await drv.revert(apply_result.confirm_token)
    assert any(c[0] == "discard_changes" for c in fake.calls)


@pytest.mark.asyncio
async def test_confirm_rejects_token_mismatch() -> None:
    drv, _fake = _make_driver()
    with pytest.raises(DriverError):
        await drv.confirm("nonexistent-token")


@pytest.mark.asyncio
async def test_apply_change_missing_token_returns_failure() -> None:
    drv, _fake = _make_driver()
    diff = ConfigDiff(
        summary="x",
        raw_before="",
        raw_after="",
        commands=("<config/>",),
        metadata={},  # missing pending_token
    )
    result = await drv.apply_change(diff)
    assert result.success is False
    assert result.error is not None


# --------------------------------------------------------------------------- #
# System info parsers (protocols / services / MAC table)
# --------------------------------------------------------------------------- #
_SYS_XML = """<rpc-reply><data>
  <lldp xmlns="http://pica8.com/xorplus/lldp"><enable>true</enable>
    <advertisement-interval>30</advertisement-interval>
    <interface><name>te-1/1/1</name></interface>
    <interface><name>te-1/1/2</name></interface></lldp>
  <ospf xmlns="http://pica8.com/xorplus/ospfv2"><router-id>10.10.250.2</router-id>
    <interface><name>vlan1010</name><area>0.0.0.0</area></interface></ospf>
  <spanning-tree xmlns="http://pica8.com/xorplus/mstp"><enable>true</enable>
    <force-version>3</force-version>
    <pvst><vlan><id>1</id><bridge-priority>32768</bridge-priority></vlan></pvst></spanning-tree>
  <dhcp>false</dhcp>
  <system xmlns="http://pica8.com/xorplus/system"><services>
    <ssh><port>22</port><disable>false</disable></ssh>
    <web><disable>false</disable>
      <http><port>80</port><disable>false</disable></http>
      <https><port>443</port><disable>false</disable></https>
    </web>
  </services></system>
</data></rpc-reply>"""


def test_parse_protocols_xml_detail_and_validity() -> None:
    protos = {p.name: p for p in _parse_protocols_xml(_SYS_XML)}
    # LLDP: interface count + advertisement interval surfaced as params
    assert dict(protos["LLDP"].params)["Interfaces"] == "2"
    assert dict(protos["LLDP"].params)["Advertisement interval"] == "30s"
    # OSPF router-id + area
    assert dict(protos["OSPF"].params)["Router ID"] == "10.10.250.2"
    # STP force-version 3 -> RSTP/MSTP
    assert dict(protos["Spanning Tree"].params)["Mode"] == "RSTP/MSTP"
    # DHCP is <dhcp>false</dhcp>: present but DISABLED, not an enabled protocol
    assert protos["DHCP"].enabled is False


def test_parse_services_xml_ssh_and_web() -> None:
    svcs = {s.name: s for s in _parse_services_xml(_SYS_XML)}
    assert svcs["SSH"].port == 22 and svcs["SSH"].enabled
    assert svcs["Web (HTTP)"].port == 80
    assert svcs["Web (HTTPS)"].port == 443 and svcs["Web (HTTPS)"].enabled


_MAC_OUT = """admin@leaf-02>
.
Total entries in switching table:   2
VLAN      MAC address          Type         Age     Interfaces         User
----      -----------------    ---------    ----    ----------------   ----------
1         64:9d:99:d9:83:ac    Dynamic      300     xe-1/1/31.1        xorp
1050      bc:24:11:13:99:3e    Static       -       xe-1/1/24          xorp
"""


def test_parse_mac_table_rows() -> None:
    rows = _parse_mac_table(_MAC_OUT)
    assert len(rows) == 2
    assert rows[0].vlan == 1 and rows[0].mac == "64:9d:99:d9:83:ac"
    assert rows[0].type == "Dynamic" and rows[0].interface == "xe-1/1/31.1"
    assert rows[1].vlan == 1050 and rows[1].type == "Static"


def test_parse_mac_table_skips_banner_and_junk() -> None:
    assert _parse_mac_table("Welcome to PICOS\nadmin@leaf-02>\ngarbage line\n") == ()
