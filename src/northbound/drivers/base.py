"""Driver ABC — the plugin contract.

Every platform adapter subclasses :class:`Driver` and registers itself
via :func:`northbound.drivers.registry.register`. The wizard, API, and UI
all consume drivers generically through this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from northbound.schemas.driver import (
    ApplyResult,
    ConfigDiff,
    ConnectionParams,
    Credentials,
    DiscoveryResult,
    DriverCapabilities,
    L3Change,
    L3Interface,
    Neighbor,
    PortChange,
    PortState,
    ProtocolDetail,
    SystemInfo,
    TestResult,
    VlanChange,
    VlanInfo,
)


class DriverError(Exception):
    """Base class for driver-layer failures."""


class NotSupported(DriverError):
    """Operation is not supported by this platform."""


class AuthError(DriverError):
    """Credentials were rejected by the device."""


class ReachabilityError(DriverError):
    """Device is unreachable at the network layer."""


class ReadOnlyDevice(DriverError):
    """Write attempted against a read-only platform."""


class Driver(ABC):
    """Plugin contract. Each platform = one subclass + registry entry."""

    capabilities: ClassVar[DriverCapabilities]
    platform_id: ClassVar[str]
    display_name: ClassVar[str]

    def __init__(self, conn: ConnectionParams, creds: Credentials) -> None:
        self._conn = conn
        self._creds = creds

    # ---------- lifecycle ----------

    async def aclose(self) -> None:
        """Release any transport the driver holds (http sockets, etc.).

        Default is a no-op for drivers with no persistent transport (e.g.
        mock, or the connection-per-run SSH path). Drivers that hold an
        ``HttpxClient`` override this. MUST be idempotent and MUST NOT raise —
        callers invoke it from ``finally`` blocks.
        """
        return None

    async def __aenter__(self) -> Driver:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ---------- onboarding ----------

    @abstractmethod
    async def test_credentials(self) -> TestResult:
        """Probe the device with the supplied creds. Cheap, idempotent."""

    @abstractmethod
    async def discover(self) -> DiscoveryResult:
        """Snapshot the device for onboarding: ports, config, services."""

    # ---------- read ----------

    @abstractmethod
    async def reachable(self) -> bool:
        """Is the device reachable right now?"""

    @abstractmethod
    async def get_ports(self) -> list[PortState]:
        """Live port inventory + per-port state."""

    @abstractmethod
    async def get_running_config(self) -> str:
        """Raw running-config as the device returns it."""

    @abstractmethod
    async def backup_config(self) -> str:
        """Opaque blob suitable for archival. May equal running-config."""

    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]:
        """LLDP neighbors. Default: none. Override per platform."""
        return []

    async def get_system_info(self) -> SystemInfo:
        """Live system snapshot: protocols, mgmt services, MAC table.

        Default: empty (no sections, MAC unsupported). Override per platform
        to fill what the driver's transport can reach.
        """
        return SystemInfo()

    async def get_protocol_detail(self, slug: str) -> ProtocolDetail:
        """Operational detail (named tables) for one protocol. Default: empty."""
        return ProtocolDetail(slug=slug)

    async def get_vlans(self) -> list[VlanInfo]:
        """The device's VLAN database (id/name/description/SVI/usage). Default: none."""
        return []

    async def get_l3_interfaces(self) -> list[L3Interface]:
        """Addressed/non-switchport interfaces: management, SVIs, LAGs. Default: none."""
        return []

    # ---------- write (NotSupported if writable=False) ----------

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        raise NotSupported(f"{self.platform_id}: render_change not supported")

    async def render_vlan_change(self, change: VlanChange) -> ConfigDiff:
        """Render a VLAN-database create/delete. Default: unsupported.

        Drivers that can write the VLAN table override this; the apply flow maps
        :class:`NotSupported` to a clear error so unsupported platforms fail
        cleanly rather than silently no-op."""
        raise NotSupported(f"{self.platform_id}: render_vlan_change not supported")

    async def render_l3_change(self, change: L3Change) -> ConfigDiff:
        """Render a routed-interface (SVI / loopback) create/delete. Default:
        unsupported — drivers that can write L3 config override this."""
        raise NotSupported(f"{self.platform_id}: render_l3_change not supported")

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        raise NotSupported(f"{self.platform_id}: apply_change not supported")

    async def confirm(self, apply_token: str) -> None:
        raise NotSupported(f"{self.platform_id}: confirm not supported")

    async def revert(self, apply_token: str) -> None:
        raise NotSupported(f"{self.platform_id}: revert not supported")
