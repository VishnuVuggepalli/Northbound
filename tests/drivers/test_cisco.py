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
    _join_config,
    _merge_port_state,
    _parse_interfaces,
    _parse_lldp,
    _parse_speed,
    _parse_switchport,
    _parse_trunk_allowed,
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
    assert "  switchport trunk allowed vlan add 100,200,300" in cmds


def test_join_config_wraps_configure_terminal() -> None:
    payload = _join_config(("interface Ethernet1/1", "  switchport access vlan 10"))
    assert payload.startswith("configure terminal ; ")
    assert "interface Ethernet1/1" in payload
    assert "switchport access vlan 10" in payload


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


@pytest.mark.asyncio
async def test_apply_change_creates_checkpoint_and_arms_rollback() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append(str(body["params"]["cmd"]))
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": 1})

    drv = _make_driver(handler=handler)
    diff = await drv.render_change("Ethernet1/1", PortChange(untagged_vlan=10))
    checkpoint = diff.metadata["checkpoint_name"]
    result = await drv.apply_change(diff, confirm_seconds=30)
    assert result.success is True
    assert result.confirm_token == checkpoint
    assert result.confirm_deadline_at is not None
    assert any(c == f"checkpoint {checkpoint}" for c in seen)
    assert any("configure terminal" in c for c in seen)
    assert any(c == f"rollback running-config checkpoint {checkpoint} delay 30" for c in seen)


@pytest.mark.asyncio
async def test_confirm_cancels_rollback_and_drops_checkpoint() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append(str(body["params"]["cmd"]))
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": 1})

    drv = _make_driver(handler=handler)
    await drv.confirm("nb-deadbeef")
    assert "no rollback running-config checkpoint nb-deadbeef delay" in seen
    assert "no checkpoint nb-deadbeef" in seen


@pytest.mark.asyncio
async def test_revert_rolls_back_to_checkpoint() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen.append(str(body["params"]["cmd"]))
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": 1})

    drv = _make_driver(handler=handler)
    await drv.revert("nb-deadbeef")
    assert "rollback running-config checkpoint nb-deadbeef" in seen


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
