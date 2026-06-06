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
    _verify_applied,
)
from northbound.schemas.driver import (
    ConfigDiff,
    ConnectionParams,
    Credentials,
    PortChange,
    PortState,
    VlanChange,
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
    # xorplus schema: <config><interface xmlns><gigabit-ethernet><name>/<description>
    # + <family><ethernet-switching>... ; {*} = namespace-agnostic match.
    xml = _build_edit_config_xml("xe-1/1/1", PortChange(description="srv-01", untagged_vlan=10))
    root = etree.fromstring(xml.encode())
    assert root.tag == "config"
    ge = root.find(".//{*}gigabit-ethernet")
    assert ge is not None
    assert ge.findtext("{*}name") == "xe-1/1/1"
    assert ge.findtext("{*}description") == "srv-01"
    eth_sw = root.find(".//{*}ethernet-switching")
    assert eth_sw is not None and eth_sw.findtext("{*}port-mode") == "access"
    # access VLAN lives in <native-vlan-id>, not <members> (device rejects members in access)
    assert eth_sw.findtext("{*}native-vlan-id") == "10"
    assert root.find(".//{*}members") is None


def test_render_change_builds_edit_config_xml_trunk() -> None:
    xml = _build_edit_config_xml(
        "xe-1/1/3", PortChange(untagged_vlan=100, tagged_vlans=[100, 200, 300])
    )
    root = etree.fromstring(xml.encode())
    eth_sw = root.find(".//{*}ethernet-switching")
    assert eth_sw is not None
    assert eth_sw.findtext("{*}port-mode") == "trunk"
    assert eth_sw.findtext("{*}native-vlan-id") == "100"
    # tagged members are a single comma-joined <id>
    assert root.find(".//{*}members/{*}id").text == "100,200,300"


def test_render_change_description_only_xorplus_ns() -> None:
    # Description-only edit must use the xorplus interface namespace (the Junos
    # tree returned "no device/data that could be affected" on the real device).
    xml = _build_edit_config_xml("xe-1/1/1", PortChange(description="NB-TEST"))
    assert "http://pica8.com/xorplus/interface" in xml
    assert "<gigabit-ethernet>" in xml and "<unit>" not in xml


def test_render_change_mtu_and_admin_disable() -> None:
    xml = _build_edit_config_xml("xe-1/1/2", PortChange(mtu=9216, enabled=False))
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.findtext(".//{*}mtu") == "9216"
    assert root.findtext(".//{*}disable") == "true"  # enabled=False -> disable=true
    # no switching family when only mtu/enabled are set
    assert root.find(".//{*}ethernet-switching") is None


def test_render_change_explicit_access_mode() -> None:
    xml = _build_edit_config_xml("xe-1/1/2", PortChange(port_mode="access", untagged_vlan=100))
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.findtext(".//{*}port-mode") == "access"
    # xorplus access ports carry the VLAN in native-vlan-id, never in members
    assert root.findtext(".//{*}native-vlan-id") == "100"
    assert root.find(".//{*}members") is None


def test_render_change_explicit_trunk_native_and_tagged() -> None:
    xml = _build_edit_config_xml(
        "xe-1/1/2", PortChange(port_mode="trunk", untagged_vlan=1010, tagged_vlans=[1002, 1003])
    )
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.findtext(".//{*}port-mode") == "trunk"
    assert root.findtext(".//{*}native-vlan-id") == "1010"
    assert root.find(".//{*}members/{*}id").text == "1002,1003"
    # The members merge is plain (no operation): the keyed <members> list is wiped
    # in render_change's phase-1 clear, so phase 2 merges into an empty list.
    vlan = root.find(".//{*}vlan")
    assert vlan is not None
    assert vlan.get("{urn:ietf:params:xml:ns:netconf:base:1.0}operation") is None


@pytest.mark.asyncio
async def test_render_change_trunk_tagged_is_two_phase() -> None:
    # Trunk tagged-VLAN write = phase 1 clear (remove <vlan>) + phase 2 set members.
    drv, _ = _make_driver()
    diff = await drv.render_change(
        "ge-1/1/1", PortChange(port_mode="trunk", untagged_vlan=10, tagged_vlans=[20, 30])
    )
    assert len(diff.commands) == 2
    phase1 = etree.fromstring(diff.commands[0].encode())
    assert (
        phase1.find(".//{*}vlan").get("{urn:ietf:params:xml:ns:netconf:base:1.0}operation")
        == "remove"
    )
    assert phase1.find(".//{*}members") is None  # phase 1 only clears
    phase2 = etree.fromstring(diff.commands[1].encode())
    assert phase2.find(".//{*}members/{*}id").text == "20,30"


@pytest.mark.asyncio
async def test_render_change_access_is_single_phase() -> None:
    drv, _ = _make_driver()
    diff = await drv.render_change("ge-1/1/1", PortChange(port_mode="access", untagged_vlan=10))
    assert len(diff.commands) == 1


@pytest.mark.asyncio
async def test_render_vlan_create() -> None:
    drv, _ = _make_driver()
    diff = await drv.render_vlan_change(VlanChange(action="create", vlan_id=1234, name="web"))
    assert len(diff.commands) == 1
    root = etree.fromstring(diff.commands[0].encode())
    assert root.find(".//{http://pica8.com/xorplus/vlans}vlans") is not None
    assert root.findtext(".//{*}id") == "1234"
    assert root.findtext(".//{*}vlan-name") == "web"
    assert "Create VLAN 1234" in diff.summary
    # No port metadata → apply_change skips the port-level readback verify.
    assert "port_name" not in diff.metadata


@pytest.mark.asyncio
async def test_render_vlan_create_defaults_name_to_id() -> None:
    drv, _ = _make_driver()
    diff = await drv.render_vlan_change(VlanChange(action="create", vlan_id=77))
    root = etree.fromstring(diff.commands[0].encode())
    assert root.findtext(".//{*}vlan-name") == "77"


@pytest.mark.asyncio
async def test_render_vlan_delete_tags_operation() -> None:
    drv, _ = _make_driver()
    diff = await drv.render_vlan_change(VlanChange(action="delete", vlan_id=1234))
    root = etree.fromstring(diff.commands[0].encode())
    vid = root.find(".//{*}vlan-id")
    assert vid is not None
    assert vid.get("{urn:ietf:params:xml:ns:netconf:base:1.0}operation") == "delete"
    assert vid.findtext("{*}id") == "1234"
    # The literal operation="delete" drives apply_change's default-operation="none".
    assert 'operation="delete"' in diff.commands[0]


def test_render_change_inferred_empty_tagged_is_access() -> None:
    # Request flow sends untagged + tagged=[] (no explicit port_mode) for an
    # access-intent change. Empty tagged MUST infer access — not trunk — else a
    # requester picking one VLAN and no tags gets a trunk port.
    xml = _build_edit_config_xml("xe-1/1/2", PortChange(untagged_vlan=100, tagged_vlans=[]))
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.findtext(".//{*}port-mode") == "access"
    assert root.findtext(".//{*}native-vlan-id") == "100"
    # access clears any trunk members (vlan removed); no members written
    vlan = root.find(".//{*}vlan")
    assert vlan is not None
    assert vlan.get("{urn:ietf:params:xml:ns:netconf:base:1.0}operation") == "remove"


def test_render_change_trunk_empty_tagged_removes_vlan() -> None:
    # Trunk with no tagged VLANs clears the member list → remove the <vlan> subtree.
    xml = _build_edit_config_xml("xe-1/1/2", PortChange(port_mode="trunk", tagged_vlans=[]))
    root = etree.fromstring(xml.encode("utf-8"))
    vlan = root.find(".//{*}vlan")
    assert vlan is not None
    assert vlan.get("{urn:ietf:params:xml:ns:netconf:base:1.0}operation") == "remove"
    assert root.find(".//{*}members") is None


def test_render_change_empty_description_emits_delete_operation() -> None:
    # xorplus ignores an empty <description/>; clearing must DELETE the node.
    xml = _build_edit_config_xml("xe-1/1/1", PortChange(description=""))
    root = etree.fromstring(xml.encode("utf-8"))
    desc = root.find(".//{*}description")
    assert desc is not None
    assert desc.get("{urn:ietf:params:xml:ns:netconf:base:1.0}operation") == "delete"


# ---------------------------------------------------------------------------
# Write-path tests — mock NetconfClient via ncclient manager_factory
# ---------------------------------------------------------------------------


_NC_BASE = "urn:ietf:params:xml:ns:netconf:base:1.0"


def _ln(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _first(el: Any, name: str) -> Any:
    return next((x for x in el.iter() if _ln(x.tag) == name), None)


def _expand(spec: str) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, _, hi = part.partition("-")
            if lo.isdigit() and hi.isdigit():
                out.update(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            out.add(int(part))
    return out


class _FakeManager:
    """Stateful fake: folds committed edit-config payloads into a per-port model
    so get_config reflects writes — lets the post-write verify run end-to-end."""

    def __init__(self, *, confirmed_commit: bool = True) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._running = _load("get_interfaces.xml")
        self._ports: dict[str, dict[str, Any]] = {}  # committed per-port facts
        self._candidate: list[str] = []  # staged (uncommitted) edit payloads
        caps = ["urn:ietf:params:netconf:base:1.0"]
        if confirmed_commit:
            caps.append("urn:ietf:params:netconf:capability:confirmed-commit:1.0")
        self.server_capabilities = caps

    def get_config(self, source: str, filter: Any = None, with_defaults: Any = None) -> str:
        self.calls.append(("get_config", (source,)))
        if not self._ports:
            return self._running  # untouched fixture for read-path tests
        return self._render()

    def _render(self) -> str:
        blocks = []
        for name, p in self._ports.items():
            sw = ""
            if "port-mode" in p or "native-vlan-id" in p or p.get("members"):
                inner = ""
                if "port-mode" in p:
                    inner += f"<port-mode>{p['port-mode']}</port-mode>"
                if "native-vlan-id" in p:
                    inner += f"<native-vlan-id>{p['native-vlan-id']}</native-vlan-id>"
                if p.get("members"):
                    ids = ",".join(str(v) for v in sorted(p["members"]))
                    inner += f"<vlan><members><id>{ids}</id></members></vlan>"
                sw = f"<family><ethernet-switching>{inner}</ethernet-switching></family>"
            extra = "".join(
                f"<{t}>{p[t]}</{t}>" for t in ("description", "mtu", "disable") if t in p
            )
            blocks.append(f"<gigabit-ethernet><name>{name}</name>{extra}{sw}</gigabit-ethernet>")
        ns = "http://pica8.com/xorplus/interface"
        return (
            f'<configuration><interface xmlns="{ns}">{"".join(blocks)}</interface></configuration>'
        )

    def _fold(self, payload: str) -> None:
        ge = _first(etree.fromstring(payload.encode()), "gigabit-ethernet")
        if ge is None:
            return
        name = (_first(ge, "name").text or "").strip()
        p = self._ports.setdefault(name, {})
        desc = _first(ge, "description")
        if desc is not None:
            if desc.get(f"{{{_NC_BASE}}}operation") == "delete":
                p.pop("description", None)
            else:
                p["description"] = desc.text or ""
        for tag in ("mtu", "disable", "port-mode", "native-vlan-id"):
            el = _first(ge, tag)
            if el is not None and el.text:
                p[tag] = el.text.strip()
        vlan = _first(ge, "vlan")
        if vlan is not None:
            if vlan.get(f"{{{_NC_BASE}}}operation") == "remove":
                p["members"] = set()
            else:
                idel = _first(vlan, "id")
                if idel is not None and idel.text:
                    p["members"] = _expand(idel.text)

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
        self._candidate.append(config)
        return "<ok/>"

    def commit(
        self,
        confirmed: bool = False,
        timeout: int | None = None,
        persist: Any = None,
        persist_id: Any = None,
    ) -> str:
        self.calls.append(("commit", (confirmed, timeout)))
        for payload in self._candidate:
            self._fold(payload)
        self._candidate.clear()
        return "<ok/>"

    def discard_changes(self) -> str:
        self.calls.append(("discard_changes", ()))
        self._candidate.clear()
        return "<ok/>"

    def close_session(self) -> None:
        self.calls.append(("close_session", ()))


def _make_driver(*, confirmed_commit: bool = True) -> tuple[Pica8Driver, _FakeManager]:
    fake = _FakeManager(confirmed_commit=confirmed_commit)
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
async def test_apply_change_discards_candidate_before_edit() -> None:
    # Regression: a prior failed apply can leave its edit staged in the candidate.
    # apply_change must discard BEFORE edit_config, else retries stack <interface>
    # blocks and commit fails with 'Duplicate key "interface:id"'.
    drv, fake = _make_driver()
    diff = await drv.render_change("ge-1/1/1", PortChange(untagged_vlan=10))
    await drv.apply_change(diff)
    ops = [c[0] for c in fake.calls]
    assert "discard_changes" in ops
    assert ops.index("discard_changes") < ops.index("edit_config")


@pytest.mark.asyncio
async def test_apply_change_trunk_tagged_is_atomic_single_commit() -> None:
    # A trunk tagged-VLAN write stages BOTH edits (clear + set) into one candidate
    # and commits ONCE — atomic. A per-phase commit could leave the clear committed
    # but the set not, wiping the trunk's tagged VLANs with no rollback.
    drv, fake = _make_driver()
    diff = await drv.render_change(
        "ge-1/1/1", PortChange(port_mode="trunk", untagged_vlan=10, tagged_vlans=[20, 30])
    )
    assert len(diff.commands) == 2  # clear + set
    result = await drv.apply_change(diff)
    assert result.success is True
    ops = [c[0] for c in fake.calls]
    assert ops.count("edit_config") == 2
    assert ops.count("commit") == 1  # single commit → atomic
    # both edits precede the one commit
    assert ops.index("commit") > max(i for i, o in enumerate(ops) if o == "edit_config")


@pytest.mark.asyncio
async def test_apply_change_discards_candidate_on_failure() -> None:
    # A rejected edit/commit must not leave the candidate dirty for the next apply.
    drv, fake = _make_driver()

    def _boom(*_a: object, **_k: object) -> str:
        raise RuntimeError("Datastore fails to validate")

    fake.commit = _boom  # type: ignore[assignment, method-assign]
    diff = await drv.render_change("ge-1/1/1", PortChange(untagged_vlan=10))
    result = await drv.apply_change(diff)
    assert result.success is False
    # discard called twice: once pre-edit, once on the failure path.
    assert [c[0] for c in fake.calls].count("discard_changes") >= 2


@pytest.mark.asyncio
async def test_apply_change_falls_back_to_plain_commit_without_capability() -> None:
    # PicOS/xorplus does NOT advertise :confirmed-commit. apply_change must do a
    # plain commit (permanent now) and return no confirm token / deadline.
    drv, fake = _make_driver(confirmed_commit=False)
    diff = await drv.render_change("ge-1/1/1", PortChange(untagged_vlan=10))
    result = await drv.apply_change(diff, confirm_seconds=45)
    assert result.success is True
    assert result.confirm_token is None
    assert result.confirm_deadline_at is None
    commit_call = next(c for c in fake.calls if c[0] == "commit")
    confirmed, timeout = commit_call[1]
    assert confirmed is False
    assert timeout is None


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


def test_parse_services_xml_canonical_set_with_absent() -> None:
    svcs = {s.name: s for s in _parse_services_xml(_SYS_XML)}
    # present-in-config services carry real state
    assert svcs["SSH"].port == 22 and svcs["SSH"].enabled and svcs["SSH"].configured
    assert svcs["Web (HTTP)"].port == 80 and svcs["Web (HTTP)"].configured
    assert svcs["Web (HTTPS)"].port == 443 and svcs["Web (HTTPS)"].enabled
    # NETCONF: we read the config over it -> present + enabled
    assert svcs["NETCONF"].enabled and svcs["NETCONF"].configured


def test_parse_services_xml_marks_absent_not_configured() -> None:
    # No <services> block at all: every canonical service is reported absent.
    svcs = {s.name: s for s in _parse_services_xml("<rpc-reply><data></data></rpc-reply>")}
    assert {"SSH", "Web (HTTP)", "Web (HTTPS)", "NETCONF"} <= set(svcs)
    assert svcs["SSH"].configured is False and svcs["SSH"].enabled is False
    # NETCONF still present (root parsed ⇒ reachable over netconf)
    assert svcs["NETCONF"].configured is True


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


_VLANS_XML = """<rpc-reply><data>
  <vlans xmlns="http://pica8.com/xorplus/vlans">
    <vlan-id><id>1</id><vlan-name>default</vlan-name></vlan-id>
    <vlan-id><id>1010</id><vlan-name>default</vlan-name><l3-interface>vlan1010</l3-interface></vlan-id>
    <vlan-id><id>2004</id><vlan-name>2004</vlan-name><description>prod</description></vlan-id>
  </vlans>
</data></rpc-reply>"""


def test_parse_vlans_xml() -> None:
    from northbound.drivers.pica8 import _parse_vlans_xml

    vlans = {v.vlan_id: v for v in _parse_vlans_xml(_VLANS_XML, {1010: 14, 2004: 2})}
    assert set(vlans) == {1, 1010, 2004}
    assert vlans[1010].l3_interface == "vlan1010" and vlans[1010].port_count == 14
    assert vlans[2004].name == "2004" and vlans[2004].description == "prod"
    assert vlans[1].port_count == 0


_SHOW_INTERFACE = """Physical interface: xe-1/1/1, Enabled, error-discard False, Physical link is Down
Port mode: trunk
Link-level type: Ethernet, MTU: 9220, Speed: Auto, Duplex: Full, FEC Enable: False
Current address: 64:9d:99:d2:6f:d4, Hardware address: 64:9d:99:d2:6f:d4
Physical interface: xe-1/1/9, Enabled, error-discard False, Physical link is Up
Port mode: access
Link-level type: Ethernet, MTU: 1558, Speed: 40Gb/s, Duplex: Full, FEC Enable: False
Current address: 64:9d:99:d2:6f:aa, Hardware address: 64:9d:99:d2:6f:aa
"""


def test_speed_to_mbps() -> None:
    from northbound.drivers.pica8 import _speed_to_mbps

    assert _speed_to_mbps("40Gb/s") == 40000
    assert _speed_to_mbps("10Gb/s") == 10000
    assert _speed_to_mbps("1000") == 1000
    assert _speed_to_mbps("100Mb/s") == 100
    assert _speed_to_mbps("Auto") is None
    assert _speed_to_mbps("") is None


def test_parse_interface_oper_and_merge() -> None:
    from northbound.drivers.pica8 import _merge_oper, _parse_interface_oper

    oper = _parse_interface_oper(_SHOW_INTERFACE)
    assert oper["xe-1/1/9"]["link_up"] is True
    assert oper["xe-1/1/9"]["speed_mbps"] == 40000
    assert oper["xe-1/1/9"]["duplex"] == "full"
    assert oper["xe-1/1/9"]["mac"] == "64:9d:99:d2:6f:aa"
    assert oper["xe-1/1/1"]["link_up"] is False and oper["xe-1/1/1"]["speed_mbps"] is None

    merged = _merge_oper(_port("xe-1/1/9"), oper["xe-1/1/9"])
    assert merged.speed_mbps == 40000 and merged.duplex == "full"
    assert merged.mac == "64:9d:99:d2:6f:aa" and merged.link_up is True
    # no oper data -> unchanged
    assert _merge_oper(_port("x"), None).speed_mbps is None


_TRUNK_IFACE = """<rpc-reply><data>
  <interface xmlns="http://pica8.com/xorplus/interface">
    <gigabit-ethernet>
      <name>xe-1/1/9</name><mtu>1554</mtu><disable>false</disable>
      <family><ethernet-switching>
        <native-vlan-id>1065</native-vlan-id>
        <port-mode>trunk</port-mode>
        <vlan><members><id>1000-1002,1065,1070</id></members></vlan>
      </ethernet-switching></family>
    </gigabit-ethernet>
  </interface>
</data></rpc-reply>"""


def test_expand_vlan_range() -> None:
    from northbound.drivers.pica8 import _expand_vlan_range

    assert _expand_vlan_range("1000-1002,1010,1050-1051") == [1000, 1001, 1002, 1010, 1050, 1051]
    assert _expand_vlan_range("") == []
    assert _expand_vlan_range("42") == [42]


def test_parse_interfaces_trunk_members_range() -> None:
    # The NETCONF way: <family><ethernet-switching><vlan><members><id>RANGE.
    ports = {p.name: p for p in _parse_interfaces_xml(_TRUNK_IFACE)}
    p = ports["xe-1/1/9"]
    assert p.untagged_vlan == 1065  # native
    # native excluded from tagged; range expanded
    assert p.tagged_vlans == (1000, 1001, 1002, 1070)


# ---------------------------------------------------------------------------
# Post-write verification (_verify_applied) — catches a commit the device
# accepted but did not fully apply.
# ---------------------------------------------------------------------------
_NS = 'xmlns="http://pica8.com/xorplus/interface"'


def _cfg(
    port: str,
    *,
    port_mode: str,
    native: str,
    members: str = "",
    mtu: str = "9216",
    disable: str = "false",
    desc: str | None = None,
) -> str:
    d = f"<description>{desc}</description>" if desc is not None else ""
    mem = f"<vlan><members><id>{members}</id></members></vlan>" if members else ""
    return (
        f"<configuration><interface {_NS}><gigabit-ethernet><name>{port}</name>"
        f"{d}<mtu>{mtu}</mtu><disable>{disable}</disable>"
        f"<family><ethernet-switching><port-mode>{port_mode}</port-mode>"
        f"<native-vlan-id>{native}</native-vlan-id>{mem}</ethernet-switching></family>"
        f"</gigabit-ethernet></interface></configuration>"
    )


def test_verify_applied_match_returns_none() -> None:
    cfg = _cfg("xe-1/1/2", port_mode="trunk", native="1010", members="1002,1003")
    change = PortChange(port_mode="trunk", untagged_vlan=1010, tagged_vlans=[1002, 1003])
    assert _verify_applied(cfg, "xe-1/1/2", change) is None


def test_verify_applied_detects_stuck_trunk_mode() -> None:
    # Intent access, but the device left port-mode trunk (the real quirk).
    cfg = _cfg("xe-1/1/2", port_mode="trunk", native="1002", members="")
    change = PortChange(port_mode="access", untagged_vlan=1002)
    drift = _verify_applied(cfg, "xe-1/1/2", change)
    assert drift is not None and "port-mode" in drift


def test_verify_applied_detects_wrong_tagged_set() -> None:
    cfg = _cfg("xe-1/1/2", port_mode="trunk", native="1010", members="1002")
    change = PortChange(port_mode="trunk", untagged_vlan=1010, tagged_vlans=[1002, 1003])
    drift = _verify_applied(cfg, "xe-1/1/2", change)
    assert drift is not None and "tagged" in drift


def test_verify_applied_missing_port() -> None:
    cfg = _cfg("xe-1/1/2", port_mode="trunk", native="1010")
    assert _verify_applied(cfg, "xe-9/9/9", PortChange(mtu=1500)) is not None


@pytest.mark.asyncio
async def test_apply_change_fails_when_device_does_not_apply() -> None:
    # Simulate the device quirk: commit succeeds but the port-mode flip is dropped.
    # apply_change must report failure, not a false success.
    drv, fake = _make_driver(confirmed_commit=False)

    real_fold = fake._fold

    def _stuck_trunk(payload: str) -> None:
        real_fold(payload)
        for p in fake._ports.values():
            p["port-mode"] = "trunk"  # device ignored the access flip, stayed trunk

    fake._fold = _stuck_trunk  # type: ignore[assignment, method-assign]
    diff = await drv.render_change("ge-1/1/1", PortChange(port_mode="access", untagged_vlan=10))
    result = await drv.apply_change(diff)
    assert result.success is False
    assert "not fully applied" in (result.error or "")
