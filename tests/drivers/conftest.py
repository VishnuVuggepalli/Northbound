"""Per-driver test fixtures.

The contract suite (``test_contract.py``) is parametrized over every
registered driver. Real-network drivers (Arista eAPI, Pica8 NETCONF) would
hit a switch in the lab if instantiated naively — that's not OK in CI.

This conftest provides a ``driver_factory`` fixture that returns a
platform-aware factory: it injects mocked transports for the real drivers
and leaves ``MockDriver`` untouched.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from northbound._lib.transport.httpx_client import HttpxClient, HttpxParams
from northbound._lib.transport.netconf_client import NetconfClient, NetconfParams
from northbound.drivers.base import Driver
from northbound.schemas.driver import ConnectionParams, Credentials

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Arista — mock the eAPI HTTPX transport with canned JSON responses
# ---------------------------------------------------------------------------


def _arista_fixture(name: str) -> object:
    return json.loads((_FIXTURE_DIR / "arista" / name).read_text())


def _arista_handler(request: httpx.Request) -> httpx.Response:
    """Route ``runCmds`` requests to canned fixtures by command list."""
    body = json.loads(request.content.decode("utf-8"))
    cmds = body.get("params", {}).get("cmds", [])
    fmt = body.get("params", {}).get("format", "json")
    result: list[Any] = []
    for cmd in cmds:
        if cmd == "show version":
            result.append(_arista_fixture("show_version.json"))
        elif cmd == "show hostname":
            result.append({"hostname": "arista-leaf-01", "fqdn": "arista-leaf-01.lab"})
        elif cmd == "show running-config":
            # text format returns {output: "..."}
            result.append({"output": "! Arista lab running-config\nhostname arista-leaf-01\n"})
        elif cmd == "show interfaces":
            result.append(_arista_fixture("show_interfaces.json"))
        elif cmd == "show interfaces switchport":
            result.append(_arista_fixture("show_switchport.json"))
        elif cmd == "show lldp neighbors detail":
            result.append(_arista_fixture("show_lldp.json"))
        elif (
            cmd == "enable"
            or cmd.startswith("configure session")
            or cmd.startswith("commit")
            or cmd == "abort"
            or cmd.startswith("interface ")
            or cmd.strip().startswith(("description", "switchport", "no "))
        ):
            result.append({})
        else:
            # Unknown command — return empty dict so the wire never breaks.
            result.append({})
    _ = fmt  # eAPI's format hint is honoured by real device; ignored here.
    return httpx.Response(200, json={"jsonrpc": "2.0", "result": result, "id": body.get("id")})


def _build_arista_http_client() -> HttpxClient:
    client = HttpxClient(HttpxParams(base_url="https://arista.test", verify_tls=False))
    client._client._transport = httpx.MockTransport(_arista_handler)  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Cisco NX-OS — mock the NX-API HTTPX transport with canned JSON-RPC responses
# ---------------------------------------------------------------------------


def _cisco_fixture(name: str) -> object:
    """Return the parsed JSON-RPC envelope for a Cisco NX-API fixture."""
    return json.loads((_FIXTURE_DIR / "cisco" / name).read_text())


def _cisco_handler(request: httpx.Request) -> httpx.Response:
    """Route NX-API ``cli`` / ``cli_ascii`` requests to canned fixtures.

    NX-API takes a single ``cmd`` (not a list). Read commands map to the
    fixture envelopes; config / checkpoint / rollback commands return a
    null-result envelope (NX-OS returns no body on successful config).
    """
    body = json.loads(request.content.decode("utf-8"))
    method = body.get("method", "cli")
    cmd = str(body.get("params", {}).get("cmd", ""))
    rid = body.get("id", 1)

    fixture_map = {
        "show interface": "show_interface.json",
        "show interface switchport": "show_interface_switchport.json",
        "show vlan": "show_vlan.json",
        "show lldp neighbors detail": "show_lldp_neighbors_detail.json",
        "show version": "show_version.json",
    }
    if cmd in fixture_map:
        env = _cisco_fixture(fixture_map[cmd])
        return httpx.Response(200, json=env)
    if cmd == "show hostname":
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "result": {"body": {"hostname": "nexus-leaf-01"}}, "id": rid},
        )
    if cmd == "show clock":
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": {"body": {"simple_time": "12:00:00 UTC"}},
                "id": rid,
            },
        )
    if cmd == "show running-config" and method == "cli_ascii":
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": {"msg": "! Cisco NX-OS running-config\nhostname nexus-leaf-01\n"},
                "id": rid,
            },
        )
    # Config / checkpoint / rollback commands: NX-OS returns null result.
    return httpx.Response(200, json={"jsonrpc": "2.0", "result": None, "id": rid})


def _build_cisco_http_client() -> HttpxClient:
    client = HttpxClient(HttpxParams(base_url="https://cisco.test", verify_tls=False))
    client._client._transport = httpx.MockTransport(_cisco_handler)  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Pica8 — mock the ncclient manager with a fake that serves the XML fixture
# ---------------------------------------------------------------------------


class _FakePica8Manager:
    """Stand-in for ncclient.manager.Manager.

    Returns the canned interface XML on ``get_config`` and records all
    write-path calls so tests can assert on them.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._running = (_FIXTURE_DIR / "pica8" / "get_interfaces.xml").read_text()

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


def _build_pica8_netconf_client() -> NetconfClient:
    fake = _FakePica8Manager()
    return NetconfClient(
        NetconfParams(host="pica8.test", username="u", password="p"),
        manager_factory=lambda: fake,
    )


# ---------------------------------------------------------------------------
# The factory the contract suite consumes
# ---------------------------------------------------------------------------


@pytest.fixture
def driver_factory() -> Callable[[type[Driver]], Driver]:
    """Build a driver instance with a platform-appropriate mocked transport."""

    conn = ConnectionParams(host="127.0.0.1")
    creds = Credentials(username="x", password="y")

    def factory(cls: type[Driver]) -> Driver:
        if cls.platform_id == "arista":
            return cls(conn, creds, http=_build_arista_http_client())  # type: ignore[call-arg]
        if cls.platform_id == "cisco":
            return cls(conn, creds, http=_build_cisco_http_client())  # type: ignore[call-arg]
        if cls.platform_id == "pica8":
            return cls(conn, creds, netconf=_build_pica8_netconf_client())  # type: ignore[call-arg]
        return cls(conn, creds)

    return factory
