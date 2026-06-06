"""MockDriver — in-memory reference implementation.

Used by:
* the contract test suite (every driver must pass; this is the harness)
* frontend dev with no real switches in the loop
* CI without lab access

Writable=True; apply is simulated with a short sleep and a token-bearing
ApplyResult so the state machine can be exercised end-to-end.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from northbound.drivers.base import Driver
from northbound.drivers.registry import register
from northbound.schemas.driver import (
    ApplyResult,
    AuthMethod,
    ConfigDiff,
    ConnectionParams,
    Credentials,
    DiscoveryResult,
    DriverCapabilities,
    Neighbor,
    PortChange,
    PortState,
    TestResult,
    VlanChange,
)


def _seed_ports() -> tuple[PortState, ...]:
    """8-port canned inventory: mix of up/down/disabled, some with descriptions."""

    def p(
        i: int,
        *,
        admin_up: bool = True,
        link_up: bool = True,
        host_model: str = "",
        bmc_ip: str = "",
        vlan: int | None = 1,
        tagged: tuple[int, ...] = (),
        description: str = "",
    ) -> PortState:
        return PortState(
            name=f"Ethernet{i}",
            admin_up=admin_up,
            link_up=link_up,
            speed_mbps=1000 if link_up else None,
            duplex="full" if link_up else None,
            mac=f"00:11:22:33:44:{i:02x}",
            mtu=1500,
            untagged_vlan=vlan,
            tagged_vlans=tagged,
            description=description,
            host_model=host_model,
            bmc_ip=bmc_ip,
            notes="",
            services={"dhcp": False, "lldp": True},
        )

    return (
        p(1, host_model="r720-01", bmc_ip="10.0.0.11", description="r720-01 idrac"),
        p(2, host_model="r720-02", bmc_ip="10.0.0.12", description="r720-02 idrac"),
        p(3, link_up=False, description="spare"),
        p(4, admin_up=False, link_up=False, description="disabled / spare"),
        p(5, vlan=100, tagged=(200, 300), description="trunk to core"),
        p(6, host_model="nas-01", bmc_ip="10.0.0.21", description="nas-01"),
        p(7, link_up=False, description=""),
        p(8, vlan=42, description="lab vlan"),
    )


_RUNNING_CONFIG = """\
! Mock device running-config
hostname mock-switch-01
!
interface Ethernet1
  description r720-01 idrac
  switchport access vlan 1
!
interface Ethernet5
  description trunk to core
  switchport mode trunk
  switchport trunk allowed vlan 100,200,300
!
end
"""


@register
class MockDriver(Driver):
    platform_id = "mock"
    display_name = "Mock (testing)"
    capabilities = DriverCapabilities(
        writable=True,
        supports_commit_confirm=True,
        native_api_available=True,
        supports_snmp_read=True,
        supports_lldp=True,
        max_concurrency=10,
        auth_methods=[AuthMethod.PASSWORD],
        web_ui_url_template=None,
    )

    def __init__(self, conn: ConnectionParams, creds: Credentials) -> None:
        super().__init__(conn, creds)
        self._ports = _seed_ports()
        self._tokens: dict[str, float] = {}

    async def test_credentials(self) -> TestResult:
        await asyncio.sleep(0)
        return TestResult(ok=True, latency_ms=1.0, platform_version="mock-1.0")

    async def discover(self) -> DiscoveryResult:
        await asyncio.sleep(0)
        return DiscoveryResult(
            hostname="mock-switch-01",
            ports=self._ports,
            running_config=_RUNNING_CONFIG,
            services={"dhcp": False, "lldp": True, "ntp": True},
        )

    async def reachable(self) -> bool:
        return True

    async def get_ports(self) -> list[PortState]:
        return list(self._ports)

    async def get_running_config(self) -> str:
        return _RUNNING_CONFIG

    async def backup_config(self) -> str:
        return _RUNNING_CONFIG

    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]:
        neighbors = [
            Neighbor(
                chassis_id="aa:bb:cc:dd:ee:01",
                port_id="Ethernet1",
                system_name="r720-01",
                system_description="Dell R720, BMC=10.0.0.11",
            ),
            Neighbor(
                chassis_id="aa:bb:cc:dd:ee:02",
                port_id="Ethernet2",
                system_name="r720-02",
                system_description="Dell R720, BMC=10.0.0.12",
            ),
            Neighbor(
                chassis_id="aa:bb:cc:dd:ee:05",
                port_id="Ethernet5",
                system_name="core-switch",
                system_description="Trunk uplink",
            ),
        ]
        if port is None:
            return neighbors
        return [n for n in neighbors if n.port_id == port]

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        await asyncio.sleep(0)
        cmds: list[str] = [f"interface {port}"]
        if change.description is not None:
            cmds.append(f"  description {change.description}")
        if change.untagged_vlan is not None:
            cmds.append(f"  switchport access vlan {change.untagged_vlan}")
        if change.tagged_vlans is not None:
            cmds.append("  switchport mode trunk")
            cmds.append(
                "  switchport trunk allowed vlan " + ",".join(str(v) for v in change.tagged_vlans)
            )
        summary = f"Update {port}"
        return ConfigDiff(
            summary=summary,
            raw_before=f"interface {port}\n  ! (previous)\n",
            raw_after="\n".join(cmds) + "\n",
            commands=tuple(cmds),
        )

    async def render_vlan_change(self, change: VlanChange) -> ConfigDiff:
        await asyncio.sleep(0)
        if change.action == "create":
            cmds = [f"vlan {change.vlan_id}"]
            if change.name:
                cmds.append(f"  name {change.name}")
            summary = f"Create VLAN {change.vlan_id}"
            before = f"! VLAN {change.vlan_id} absent\n"
        else:
            cmds = [f"no vlan {change.vlan_id}"]
            summary = f"Delete VLAN {change.vlan_id}"
            before = f"vlan {change.vlan_id}\n"
        return ConfigDiff(
            summary=summary,
            raw_before=before,
            raw_after="\n".join(cmds) + "\n",
            commands=tuple(cmds),
        )

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        await asyncio.sleep(0.1)
        token = f"mock-{uuid.uuid4().hex[:12]}"
        deadline = time.time() + confirm_seconds
        self._tokens[token] = deadline
        return ApplyResult(
            success=True,
            confirm_token=token,
            confirm_deadline_at=deadline,
            error=None,
        )

    async def confirm(self, apply_token: str) -> None:
        await asyncio.sleep(0)
        self._tokens.pop(apply_token, None)

    async def revert(self, apply_token: str) -> None:
        await asyncio.sleep(0)
        self._tokens.pop(apply_token, None)
