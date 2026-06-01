"""CiscoDriver — parser + write-path unit tests.

NX-API transport is mocked via ``httpx.MockTransport``; no live network.
Parser tests operate on the ``body`` of canned JSON-RPC envelopes under
``tests/fixtures/cisco/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams
from northbound.drivers.cisco import (
    CiscoDriver,
    _build_change_commands,
    _config_lines,
    _merge_port_state,
    _parse_interfaces,
    _parse_interfaces_status_text,
    _parse_lldp,
    _parse_lldp_text,
    _parse_speed,
    _parse_switchport,
    _parse_trunk_allowed,
    _raise_for_config_errors,
)
from northbound.schemas.driver import (
    ConnectionParams,
    Credentials,
    PortChange,
    PortState,
)

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "cisco"


def _body(name: str) -> Any:
    """Return the ``result.body`` from a canned NX-API JSON-RPC envelope."""
    env = json.loads((_FIXTURE_DIR / name).read_text())
    return env["result"]["body"]


# ---------------------------------------------------------------------------
# Pure parser tests — no transport
# ---------------------------------------------------------------------------


# Real `show interfaces status` output captured live from IOSvL2 15.2 (the
# "Name" column is blank — the case that broke the old hand-rolled parser). This
# locks in the ntc-templates-backed parse: routed→None, access VLAN extracted,
# shutdown→admin_up False.
_IOS_IF_STATUS = """
Port      Name               Status       Vlan       Duplex  Speed Type
Gi0/0                        connected    routed     a-full   auto RJ45
Gi0/1                        connected    20         a-full   auto RJ45
Gi0/2                        connected    1          a-full   auto RJ45
Gi0/3                        disabled     1          auto     auto RJ45
"""


def test_parse_interfaces_status_text_via_ntc_templates() -> None:
    ports = {p.name: p for p in _parse_interfaces_status_text(_IOS_IF_STATUS)}
    assert set(ports) == {"Gi0/0", "Gi0/1", "Gi0/2", "Gi0/3"}
    assert ports["Gi0/0"].untagged_vlan is None  # 'routed' is not a VLAN
    assert ports["Gi0/1"].untagged_vlan == 20  # access VLAN extracted (Name col blank)
    assert ports["Gi0/2"].untagged_vlan == 1
    assert ports["Gi0/1"].link_up is True and ports["Gi0/1"].admin_up is True
    assert ports["Gi0/3"].admin_up is False  # 'disabled' = shutdown
    assert ports["Gi0/3"].link_up is False


def test_parse_interfaces_status_text_empty_on_garbage() -> None:
    # Degrades gracefully (best-effort SSH fallback), never raises.
    assert _parse_interfaces_status_text("not a real table") == []


# Real `show lldp neighbors detail` output captured live from IOSvL2.
_IOS_LLDP_DETAIL = """
------------------------------------------------
Local Intf: Gi0/1
Chassis id: 0000.0104.0891
Port id: 6aca.9317.1999
Port Description: tapA
System Name: peer-host.example

System Description:
Debian GNU/Linux 12 (bookworm)

Time remaining: 118 seconds
System Capabilities: B,R
Enabled Capabilities: B
Management Addresses - not advertised

Total entries displayed: 1
"""


def test_parse_lldp_text_via_ntc_templates() -> None:
    nbrs = _parse_lldp_text(_IOS_LLDP_DETAIL)
    assert len(nbrs) == 1
    n = nbrs[0]
    assert n.chassis_id == "0000.0104.0891"
    assert n.port_id == "6aca.9317.1999"
    assert n.system_name == "peer-host.example"
    # local port encoded as the bracketed prefix for get_neighbors(port=...)
    assert n.system_description is not None and n.system_description.startswith("[Gi0/1] ")


def test_parse_lldp_text_empty_on_garbage() -> None:
    assert _parse_lldp_text("nope") == []


def test_parse_interfaces_returns_PortState_list() -> None:
    result = _parse_interfaces(_body("show_interface.json"))
    assert len(result) == 4
    eth1 = result["Ethernet1/1"]
    assert isinstance(eth1, PortState)
    assert eth1.admin_up is True
    assert eth1.link_up is True
    assert eth1.speed_mbps == 10_000  # "10 Gb/s" → 10000 Mbps
    assert eth1.duplex == "full"
    assert eth1.description == "to-r720-01"
    assert eth1.mac == "00:1c:73:aa:bb:01"
    assert eth1.mtu == 9216


def test_parse_interfaces_admin_and_link_state() -> None:
    result = _parse_interfaces(_body("show_interface.json"))
    # Eth1/2: oper down but admin up
    assert result["Ethernet1/2"].link_up is False
    assert result["Ethernet1/2"].admin_up is True
    # Eth1/3: admin_state=down → shutdown
    assert result["Ethernet1/3"].admin_up is False
    assert result["Ethernet1/3"].link_up is False


def test_parse_switchport_assigns_vlans() -> None:
    by_name = _parse_switchport(_body("show_interface_switchport.json"))
    assert by_name["Ethernet1/1"]["mode"] == "access"
    assert by_name["Ethernet1/1"]["access_vlan"] == 10
    assert by_name["Ethernet1/4"]["mode"] == "trunk"
    assert by_name["Ethernet1/4"]["native_vlan"] == 100
    assert by_name["Ethernet1/4"]["trunk_allowed"] == "100,200,300"


def test_merge_port_state_overlays_vlans() -> None:
    interfaces = _parse_interfaces(_body("show_interface.json"))
    switchport = _parse_switchport(_body("show_interface_switchport.json"))
    merged = {p.name: p for p in _merge_port_state(interfaces, switchport)}
    assert merged["Ethernet1/1"].untagged_vlan == 10
    assert merged["Ethernet1/1"].tagged_vlans == ()
    eth4 = merged["Ethernet1/4"]
    assert eth4.untagged_vlan == 100
    assert eth4.tagged_vlans == (100, 200, 300)
    # Eth1/3 has no switchport row — base state preserved.
    assert merged["Ethernet1/3"].untagged_vlan is None


def test_parse_lldp_returns_neighbors() -> None:
    neighbors = _parse_lldp(_body("show_lldp_neighbors_detail.json"))
    assert len(neighbors) == 2
    by_chassis = {n.chassis_id: n for n in neighbors}
    assert "aa:bb:cc:dd:ee:01" in by_chassis
    assert by_chassis["aa:bb:cc:dd:ee:01"].system_name == "r720-01"
    desc = by_chassis["aa:bb:cc:dd:ee:01"].system_description or ""
    assert "Ethernet1/1" in desc  # local port encoded into prefix
    assert by_chassis["aa:bb:cc:dd:ee:99"].port_id == "Ethernet1/1"


def test_parse_lldp_handles_missing_table() -> None:
    assert _parse_lldp({}) == []
    assert _parse_lldp({"TABLE_nbor_detail": "garbage"}) == []


@pytest.mark.asyncio
async def test_get_neighbors_port_filter_is_exact_not_substring() -> None:
    """Port 'Eth1' must NOT match neighbors on 'Eth1/1' or 'Eth10' — the old
    substring filter (port in system_description) did. Exact bracket match."""
    table = {
        "TABLE_nbor_detail": {
            "ROW_nbor_detail": [
                {"chassis_id": "aa:aa:aa:aa:aa:01", "l_port_id": "Eth1", "sys_desc": "host-a"},
                {"chassis_id": "aa:aa:aa:aa:aa:02", "l_port_id": "Eth1/1", "sys_desc": "host-b"},
                {"chassis_id": "aa:aa:aa:aa:aa:03", "l_port_id": "Eth10", "sys_desc": "host-c"},
            ]
        }
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"body": table}})

    drv = _make_driver(handler=handler)
    eth1 = await drv.get_neighbors("Eth1")
    assert [n.chassis_id for n in eth1] == ["aa:aa:aa:aa:aa:01"]
    eth1_1 = await drv.get_neighbors("Eth1/1")
    assert [n.chassis_id for n in eth1_1] == ["aa:aa:aa:aa:aa:02"]
    eth10 = await drv.get_neighbors("Eth10")
    assert [n.chassis_id for n in eth10] == ["aa:aa:aa:aa:aa:03"]


def test_rows_collapses_single_row_object() -> None:
    # NX-OS collapses a single-row table to a bare object; parser must cope.
    single = {"TABLE_interface": {"ROW_interface": {"interface": "Ethernet1/9", "state": "up"}}}
    result = _parse_interfaces(single)
    assert "Ethernet1/9" in result


def test_parse_speed_variants() -> None:
    assert _parse_speed("10 Gb/s", None) == 10_000
    assert _parse_speed("1000 Mb/s", None) == 1000
    assert _parse_speed("auto-speed", 1000000) == 1000  # falls back to eth_bw (Kbit/s)
    assert _parse_speed("auto-speed", 0) is None


def test_parse_trunk_allowed_ignores_all_range() -> None:
    assert _parse_trunk_allowed("1-4094") == ()
    assert _parse_trunk_allowed("ALL") == ()
    assert _parse_trunk_allowed("10,20-22") == (10, 20, 21, 22)


# ---------------------------------------------------------------------------
# render_change — pure CLI generation
# ---------------------------------------------------------------------------


def test_render_change_builds_access_commands() -> None:
    cmds = _build_change_commands("Ethernet1/5", PortChange(description="srv-01", untagged_vlan=42))
    assert cmds[0] == "interface Ethernet1/5"
    assert any("description srv-01" in c for c in cmds)
    assert any("switchport mode access" in c for c in cmds)
    assert any("switchport access vlan 42" in c for c in cmds)


def test_render_change_trunk_with_tagged_and_native() -> None:
    cmds = _build_change_commands(
        "Ethernet1/9",
        PortChange(untagged_vlan=100, tagged_vlans=[100, 200, 300]),
    )
    assert "  switchport mode trunk" in cmds
    assert "  switchport trunk native vlan 100" in cmds
    # Declarative replace — NOT 'add' (which would only accumulate).
    assert "  switchport trunk allowed vlan 100,200,300" in cmds
    assert not any("allowed vlan add" in c for c in cmds)


def test_config_lines_strips_and_drops_blanks() -> None:
    lines = _config_lines(("interface Ethernet1/1", "  switchport access vlan 10", "  "))
    # configure terminal is prepended by _nxapi_cli_config, not here.
    assert lines == ["interface Ethernet1/1", "switchport access vlan 10"]


@pytest.mark.asyncio
async def test_render_change_includes_checkpoint_name() -> None:
    drv = _make_driver(handler=lambda _r: httpx.Response(200, json={"result": None}))
    diff = await drv.render_change("Ethernet1/1", PortChange(untagged_vlan=10))
    assert "checkpoint_name" in diff.metadata
    assert diff.metadata["checkpoint_name"].startswith("nb-")


# ---------------------------------------------------------------------------
# Write-path tests — mock HttpxClient, observe outgoing NX-API bodies
# ---------------------------------------------------------------------------


def _make_driver(*, handler, prefer_native_api: bool = True) -> CiscoDriver:  # type: ignore[no-untyped-def]
    http = HttpxClient(HttpxParams(base_url="https://cisco.test", verify_tls=False))
    http._client._transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    return CiscoDriver(
        ConnectionParams(host="127.0.0.1", prefer_native_api=prefer_native_api),
        Credentials(username="admin", password="pw"),
        http=http,
    )


def _nxapi_cmds(body: Any) -> list[str]:
    """Extract the cmd(s) from an NX-API body — single object OR command array."""
    objs = body if isinstance(body, list) else [body]
    return [str(o["params"]["cmd"]) for o in objs if isinstance(o, dict) and "params" in o]


def _nxapi_collect(seen: list[str]):  # type: ignore[no-untyped-def]
    """MockTransport handler recording every cmd (dict or array body) and
    returning a matching JSON-RPC response (object for one, array for many)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        cmds = _nxapi_cmds(body)
        seen.extend(cmds)
        if isinstance(body, list):
            return httpx.Response(
                200,
                json=[{"jsonrpc": "2.0", "result": None, "id": i + 1} for i in range(len(body))],
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": 1})

    return handler


@pytest.mark.asyncio
async def test_apply_change_creates_checkpoint_no_device_timer() -> None:
    """NX-OS has no device-armed rollback timer — apply must create the
    checkpoint and apply config atomically, and emit NO ``delay`` keyword.
    The confirm window is app-enforced (confirm_deadline_at)."""
    seen: list[str] = []

    drv = _make_driver(handler=_nxapi_collect(seen))
    diff = await drv.render_change("Ethernet1/1", PortChange(untagged_vlan=10))
    checkpoint = diff.metadata["checkpoint_name"]
    result = await drv.apply_change(diff, confirm_seconds=30)
    assert result.success is True
    assert result.confirm_token == checkpoint
    assert result.confirm_deadline_at is not None  # app-enforced window
    assert f"checkpoint {checkpoint}" in seen
    # Config applied via the NX-API command ARRAY led by configure terminal.
    assert "configure terminal" in seen
    assert "switchport access vlan 10" in seen
    # The fabricated device-armed rollback must be gone entirely.
    assert not any("delay" in c for c in seen)
    assert not any("rollback" in c for c in seen)


@pytest.mark.asyncio
async def test_confirm_drops_checkpoint_only() -> None:
    """confirm = ``no checkpoint <name>`` ONLY. No ``rollback ... delay``."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append(str(body["params"]["cmd"]))
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": 1})

    drv = _make_driver(handler=handler)
    await drv.confirm("nb-deadbeef")
    assert seen == ["no checkpoint nb-deadbeef"]
    assert not any("delay" in c for c in seen)
    assert not any("rollback" in c for c in seen)


@pytest.mark.asyncio
async def test_revert_rolls_back_to_checkpoint_then_cleans_up() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append(str(body["params"]["cmd"]))
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": 1})

    drv = _make_driver(handler=handler)
    await drv.revert("nb-deadbeef")
    assert seen == [
        "rollback running-config checkpoint nb-deadbeef",
        "no checkpoint nb-deadbeef",
    ]
    assert not any("delay" in c for c in seen)


@pytest.mark.asyncio
async def test_apply_change_config_is_single_atomic_request() -> None:
    """The change body (all interface lines) goes out in ONE NX-API cli
    request, not one request per line — so a mid-list failure can't leave a
    half-applied interface."""
    config_reqs: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        cmds = _nxapi_cmds(body)
        if isinstance(body, list) and "configure terminal" in cmds:
            config_reqs.append(cmds)
            return httpx.Response(
                200,
                json=[{"jsonrpc": "2.0", "result": None, "id": i + 1} for i in range(len(body))],
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": 1})

    drv = _make_driver(handler=handler)
    diff = await drv.render_change(
        "Ethernet1/9", PortChange(untagged_vlan=100, tagged_vlans=[100, 200, 300])
    )
    result = await drv.apply_change(diff, confirm_seconds=30)
    assert result.success is True
    # The whole change body goes out in ONE array request (not one per line).
    assert len(config_reqs) == 1
    one = config_reqs[0]
    assert "switchport mode trunk" in one
    assert "switchport trunk allowed vlan 100,200,300" in one


@pytest.mark.asyncio
async def test_apply_change_surfaces_per_command_error() -> None:
    """A per-command error in the NX-API result list must fail the apply,
    not be silently swallowed."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if isinstance(body, list):
            # NX-OS command-array partial failure: a per-command JSON-RPC object
            # carries its own ``error`` (HTTP 500 in real life).
            resp = [{"jsonrpc": "2.0", "result": None, "id": i + 1} for i in range(len(body))]
            resp[-1] = {
                "jsonrpc": "2.0",
                "id": len(body),
                "error": {"code": -32602, "data": {"msg": "Invalid VLAN"}},
            }
            return httpx.Response(500, json=resp)
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": 1})

    drv = _make_driver(handler=handler)
    diff = await drv.render_change("Ethernet1/1", PortChange(untagged_vlan=10))
    result = await drv.apply_change(diff)
    assert result.success is False
    assert result.error and "Invalid VLAN" in result.error


def test_raise_for_config_errors_detects_top_level_and_per_command() -> None:
    # Single object with an error (read-style response).
    with pytest.raises(Exception, match="config error"):
        _raise_for_config_errors({"error": {"code": -1, "message": "boom"}})
    # Per-command error inside the command-ARRAY response; data.msg is surfaced.
    with pytest.raises(Exception, match="Invalid VLAN"):
        _raise_for_config_errors(
            [
                {"jsonrpc": "2.0", "result": None, "id": 1},
                {"jsonrpc": "2.0", "id": 2, "error": {"data": {"msg": "Invalid VLAN"}}},
            ]
        )
    # Clean array response → no raise.
    _raise_for_config_errors([{"jsonrpc": "2.0", "result": None, "id": 1}])


@pytest.mark.asyncio
async def test_apply_change_missing_checkpoint_returns_failure() -> None:
    from northbound.schemas.driver import ConfigDiff

    drv = _make_driver(handler=lambda _r: httpx.Response(200, json={"result": None}))
    diff = ConfigDiff(summary="x", raw_before="", raw_after="", commands=("foo",))
    result = await drv.apply_change(diff)
    assert result.success is False
    assert result.confirm_token is None
    assert result.error and "checkpoint_name" in result.error


@pytest.mark.asyncio
async def test_test_credentials_auth_failure_returns_not_ok() -> None:
    drv = _make_driver(handler=lambda _r: httpx.Response(401, text="unauthorized"))
    result = await drv.test_credentials()
    assert result.ok is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_test_credentials_ok_extracts_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        env = json.loads((_FIXTURE_DIR / "show_version.json").read_text())
        return httpx.Response(200, json=env)

    drv = _make_driver(handler=handler)
    result = await drv.test_credentials()
    assert result.ok is True
    assert result.platform_version is not None
    assert "9.3(8)" in result.platform_version


# ---------------------------------------------------------------------------
# SSH fallback path — write ops are NotSupported, no HTTP transport built
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ssh_path_write_ops_not_supported() -> None:
    from northbound.drivers.base import NotSupported

    drv = CiscoDriver(
        ConnectionParams(host="127.0.0.1", prefer_native_api=False),
        Credentials(username="admin", password="pw"),
    )
    diff = await drv.render_change("Ethernet1/1", PortChange(untagged_vlan=10))
    with pytest.raises(NotSupported):
        await drv.apply_change(diff)
    with pytest.raises(NotSupported):
        await drv.confirm("nb-x")
    with pytest.raises(NotSupported):
        await drv.revert("nb-x")


@pytest.mark.asyncio
async def test_ssh_path_get_neighbors_returns_empty() -> None:
    drv = CiscoDriver(
        ConnectionParams(host="127.0.0.1", prefer_native_api=False),
        Credentials(username="admin", password="pw"),
    )
    assert await drv.get_neighbors() == []


@pytest.mark.asyncio
async def test_aclose_closes_http_and_is_idempotent() -> None:
    """aclose() closes the injected http transport exactly once and never
    raises on a second call (callers invoke it from finally blocks)."""
    closed: list[int] = []

    class _FakeHttp:
        async def aclose(self) -> None:
            closed.append(1)

    drv = CiscoDriver(
        ConnectionParams(host="127.0.0.1", prefer_native_api=True),
        Credentials(username="admin", password="pw"),
        http=_FakeHttp(),  # type: ignore[arg-type]
    )
    await drv.aclose()
    await drv.aclose()
    assert closed == [1]


@pytest.mark.asyncio
async def test_aclose_noop_on_ssh_path() -> None:
    """SSH-only driver holds no http transport — aclose() is a safe no-op."""
    drv = CiscoDriver(
        ConnectionParams(host="127.0.0.1", prefer_native_api=False),
        Credentials(username="admin", password="pw"),
    )
    await drv.aclose()  # must not raise
