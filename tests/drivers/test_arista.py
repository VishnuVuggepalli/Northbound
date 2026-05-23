"""AristaDriver — parser + write-path unit tests.

Transport is mocked via ``httpx.MockTransport``; no live network. Parser
tests work on canned JSON fixtures under ``tests/fixtures/arista/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams
from northbound.drivers.arista import (
    AristaDriver,
    _build_change_commands,
    _format_commit_timer,
    _merge_port_state,
    _parse_interfaces,
    _parse_lldp,
    _parse_switchport,
)
from northbound.schemas.driver import (
    ConnectionParams,
    Credentials,
    PortChange,
    PortState,
)

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "arista"


def _load(name: str) -> Any:
    return json.loads((_FIXTURE_DIR / name).read_text())


# ---------------------------------------------------------------------------
# Pure parser tests — no transport
# ---------------------------------------------------------------------------


def test_parse_interfaces_returns_PortState_list() -> None:
    payload = _load("show_interfaces.json")
    result = _parse_interfaces(payload)
    assert len(result) == 4
    eth1 = result["Ethernet1"]
    assert isinstance(eth1, PortState)
    assert eth1.admin_up is True
    assert eth1.link_up is True
    assert eth1.speed_mbps == 10_000  # 10 Gbps → 10000 Mbps
    assert eth1.description == "to-r720-01"
    assert eth1.mac == "00:1c:73:aa:bb:01"

    eth3 = result["Ethernet3"]
    assert eth3.admin_up is False  # interfaceStatus=disabled
    assert eth3.link_up is False


def test_parse_switchport_assigns_vlans() -> None:
    payload = _load("show_switchport.json")
    by_name = _parse_switchport(payload)
    assert by_name["Ethernet1"]["mode"] == "access"
    assert by_name["Ethernet1"]["access_vlan"] == 10
    assert by_name["Ethernet4"]["mode"] == "trunk"
    assert by_name["Ethernet4"]["native_vlan"] == 100
    assert by_name["Ethernet4"]["trunk_allowed"] == "100,200,300"


def test_merge_port_state_overlays_access_vlan() -> None:
    interfaces = _parse_interfaces(_load("show_interfaces.json"))
    switchport = _parse_switchport(_load("show_switchport.json"))
    merged = {p.name: p for p in _merge_port_state(interfaces, switchport)}
    assert merged["Ethernet1"].untagged_vlan == 10
    assert merged["Ethernet1"].tagged_vlans == ()
    eth4 = merged["Ethernet4"]
    assert eth4.untagged_vlan == 100
    assert eth4.tagged_vlans == (100, 200, 300)


def test_parse_lldp_returns_neighbors() -> None:
    payload = _load("show_lldp.json")
    neighbors = _parse_lldp(payload)
    assert len(neighbors) == 2
    by_chassis = {n.chassis_id: n for n in neighbors}
    assert "aa:bb:cc:dd:ee:01" in by_chassis
    assert by_chassis["aa:bb:cc:dd:ee:01"].system_name == "r720-01"
    # local-port should be encoded in system_description prefix
    assert by_chassis["aa:bb:cc:dd:ee:01"].system_description
    assert "Ethernet1" in (by_chassis["aa:bb:cc:dd:ee:01"].system_description or "")


def test_parse_lldp_handles_missing_table() -> None:
    assert _parse_lldp({}) == []
    assert _parse_lldp({"lldpNeighbors": "garbage"}) == []


# ---------------------------------------------------------------------------
# render_change — pure CLI generation
# ---------------------------------------------------------------------------


def test_render_change_builds_cli_commands() -> None:
    cmds = _build_change_commands("Ethernet5", PortChange(description="srv-01", untagged_vlan=42))
    assert cmds[0] == "interface Ethernet5"
    assert any("description srv-01" in c for c in cmds)
    assert any("switchport mode access" in c for c in cmds)
    assert any("switchport access vlan 42" in c for c in cmds)


def test_render_change_trunk_with_tagged_and_native() -> None:
    cmds = _build_change_commands(
        "Ethernet9",
        PortChange(untagged_vlan=100, tagged_vlans=[100, 200, 300]),
    )
    assert "  switchport mode trunk" in cmds
    assert "  switchport trunk native vlan 100" in cmds
    assert "  switchport trunk allowed vlan 100,200,300" in cmds


def test_format_commit_timer_renders_h_mm_ss() -> None:
    assert _format_commit_timer(60) == "0:01:00"
    assert _format_commit_timer(3725) == "1:02:05"
    assert _format_commit_timer(0) == "0:00:01"  # clamped to at least 1s


@pytest.mark.asyncio
async def test_render_change_includes_session_name() -> None:
    drv = _make_driver(handler=lambda _r: httpx.Response(200, json={"result": []}))
    diff = await drv.render_change("Ethernet1", PortChange(untagged_vlan=10))
    assert "session_name" in diff.metadata
    assert diff.metadata["session_name"].startswith("nb-")


# ---------------------------------------------------------------------------
# Write-path tests — mock HttpxClient, observe outgoing JSON-RPC bodies
# ---------------------------------------------------------------------------


def _make_driver(*, handler) -> AristaDriver:  # type: ignore[no-untyped-def]
    http = HttpxClient(HttpxParams(base_url="https://arista.test", verify_tls=False))
    http._client._transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    return AristaDriver(
        ConnectionParams(host="127.0.0.1"),
        Credentials(username="admin", password="pw"),
        http=http,
    )


@pytest.mark.asyncio
async def test_apply_change_wraps_in_configure_session() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen["cmds"] = body["params"]["cmds"]
        return httpx.Response(200, json={"result": [{}] * len(body["params"]["cmds"])})

    drv = _make_driver(handler=handler)
    diff = await drv.render_change("Ethernet1", PortChange(untagged_vlan=10))
    result = await drv.apply_change(diff, confirm_seconds=30)
    assert result.success is True
    cmds = seen["cmds"]
    assert any(c.startswith("configure session nb-") for c in cmds)
    assert "commit timer 0:00:30" in cmds
    # The session in apply_change must match the one in the diff.
    session_cmd = next(c for c in cmds if c.startswith("configure session"))
    assert diff.metadata["session_name"] in session_cmd


@pytest.mark.asyncio
async def test_confirm_calls_commit() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen["cmds"] = body["params"]["cmds"]
        return httpx.Response(200, json={"result": [{}] * len(body["params"]["cmds"])})

    drv = _make_driver(handler=handler)
    await drv.confirm("nb-deadbeef")
    assert "configure session nb-deadbeef" in seen["cmds"]
    assert "commit" in seen["cmds"]


@pytest.mark.asyncio
async def test_revert_calls_abort() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen["cmds"] = body["params"]["cmds"]
        return httpx.Response(200, json={"result": [{}] * len(body["params"]["cmds"])})

    drv = _make_driver(handler=handler)
    await drv.revert("nb-deadbeef")
    assert "configure session nb-deadbeef" in seen["cmds"]
    assert "abort" in seen["cmds"]


@pytest.mark.asyncio
async def test_apply_change_missing_session_returns_failure() -> None:
    from northbound.schemas.driver import ConfigDiff

    drv = _make_driver(handler=lambda _r: httpx.Response(200, json={"result": []}))
    diff = ConfigDiff(summary="x", raw_before="", raw_after="", commands=("foo",))
    result = await drv.apply_change(diff)
    assert result.success is False
    assert result.confirm_token is None
    assert result.error and "session_name" in result.error


@pytest.mark.asyncio
async def test_test_credentials_auth_failure_returns_not_ok() -> None:
    drv = _make_driver(handler=lambda _r: httpx.Response(401, text="unauthorized"))
    result = await drv.test_credentials()
    assert result.ok is False
    assert result.error is not None
