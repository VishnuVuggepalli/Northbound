"""Per-driver test fixtures.

The contract suite (``test_contract.py``) is parametrized over every
registered driver. Real-network drivers (Arista eAPI, Pica8 NETCONF) would
hit a switch in the lab if instantiated naively — that's not OK in CI.

This conftest provides a ``driver_factory`` fixture that returns a
platform-aware factory: it injects mocked transports for the real drivers
and leaves ``MockDriver`` untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from northbound._lib.transport.netconf_client import NetconfClient, NetconfParams
from northbound.drivers.base import Driver
from northbound.schemas.driver import ConnectionParams, Credentials

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Arista — inject a fake NAPALM eos device (the driver is NAPALM-backed now)
# ---------------------------------------------------------------------------


class _FakeAristaNode:
    """pyeapi node stand-in for `show interfaces switchport`."""

    def run_commands(self, cmds: list[str], encoding: str = "json") -> list[dict[str, Any]]:
        return [
            {
                "switchports": {
                    "Ethernet1": {"switchportInfo": {"mode": "access", "accessVlanId": 10}}
                }
            }
        ]


class _FakeAristaNapalm:
    """The slice of NAPALM's eos driver the AristaDriver calls (contract test)."""

    def __init__(self) -> None:
        self.device = _FakeAristaNode()

    def open(self) -> None: ...
    def close(self) -> None: ...
    def is_alive(self) -> dict[str, bool]:
        return {"is_alive": True}

    def get_facts(self) -> dict[str, str]:
        return {
            "vendor": "Arista",
            "model": "vEOS",
            "os_version": "4.27.0F",
            "hostname": "arista-leaf-01",
        }

    def get_config(self, retrieve: str = "all") -> dict[str, str]:
        return {
            "running": "! Arista lab running-config\nhostname arista-leaf-01\n",
            "candidate": "",
            "startup": "",
        }

    def get_interfaces(self) -> dict[str, Any]:
        return {"Ethernet1": {"is_enabled": True, "is_up": True, "description": "", "mtu": 1500}}

    def get_lldp_neighbors_detail(self) -> dict[str, Any]:
        return {}

    def load_merge_candidate(self, config: str | None = None) -> None: ...
    def commit_config(self, message: str = "", revert_in: int | None = None) -> None: ...
    def confirm_commit(self) -> None: ...
    def rollback(self) -> None: ...
    def discard_config(self) -> None: ...


def _build_arista_device() -> _FakeAristaNapalm:
    return _FakeAristaNapalm()


# ---------------------------------------------------------------------------
# Cisco — inject a fake NAPALM nxos device (the driver is NAPALM-backed now)
# ---------------------------------------------------------------------------

_NXOS_SWITCHPORT = (
    "Name: Ethernet1/1\n  Switchport: Enabled\n  Operational Mode: access\n"
    "  Access Mode VLAN: 10 (VLAN0010)\n"
    "  Trunking Native Mode VLAN: 1 (default)\n  Trunking VLANs Allowed: 1-4094\n"
)


class _FakeCiscoNapalm:
    """The slice of NAPALM's nxos driver the CiscoDriver calls (contract test)."""

    def open(self) -> None: ...
    def close(self) -> None: ...
    def is_alive(self) -> dict[str, bool]:
        return {"is_alive": True}

    def get_facts(self) -> dict[str, str]:
        return {"model": "N9K-v", "os_version": "9.3", "hostname": "nexus-leaf-01"}

    def get_config(self, retrieve: str = "all") -> dict[str, str]:
        return {
            "running": "! Cisco NX-OS running-config\nhostname nexus-leaf-01\n",
            "candidate": "",
            "startup": "",
        }

    def get_interfaces(self) -> dict[str, Any]:
        return {"Ethernet1/1": {"is_enabled": True, "is_up": True, "description": "", "mtu": 1500}}

    def get_lldp_neighbors_detail(self) -> dict[str, Any]:
        return {}

    def cli(self, cmds: list[str]) -> dict[str, str]:
        return {cmds[0]: _NXOS_SWITCHPORT}

    def load_merge_candidate(self, config: str | None = None) -> None: ...
    def commit_config(self, message: str = "", revert_in: int | None = None) -> None: ...
    def confirm_commit(self) -> None: ...
    def rollback(self) -> None: ...
    def discard_config(self) -> None: ...


def _build_cisco_device() -> _FakeCiscoNapalm:
    return _FakeCiscoNapalm()


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
# MikroTik — fake the RouterOS REST transport: GET /rest/<menu> serves the
# matching fixture; PATCH/POST echo a 200. Mirrors HttpxClient's get/request.
# ---------------------------------------------------------------------------
class _FakeMikrotikClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._dir = _FIXTURE_DIR / "mikrotik"

    def _load(self, menu: str) -> Any:
        import json

        path = self._dir / (menu.replace("/", "_") + ".json")
        return json.loads(path.read_text()) if path.exists() else []

    async def get(self, url: str, *, headers: Any = None, params: Any = None) -> Any:
        import httpx

        self.calls.append(("GET", url))
        menu = url.removeprefix("/rest/")
        return httpx.Response(200, json=self._load(menu))

    async def request(
        self, method: str, url: str, *, headers: Any = None, json: Any = None, params: Any = None
    ) -> Any:
        import httpx

        self.calls.append((method, url, str(json)))
        if url == "/rest/export":
            return httpx.Response(200, json=[{"ret": "# exported config\n/interface\n"}])
        return httpx.Response(200, json=json or {})

    async def aclose(self) -> None:
        return None


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
            return cls(conn, creds, device=_build_arista_device())  # type: ignore[call-arg]
        if cls.platform_id == "cisco":
            return cls(conn, creds, device=_build_cisco_device())  # type: ignore[call-arg]
        if cls.platform_id == "pica8":
            return cls(conn, creds, netconf=_build_pica8_netconf_client())  # type: ignore[call-arg]
        if cls.platform_id == "mikrotik":
            return cls(conn, creds, http=_FakeMikrotikClient())  # type: ignore[call-arg]
        return cls(conn, creds)

    return factory
