"""Driver layer schemas.

Pydantic v2 models for API-facing payloads, frozen dataclasses for the
in-process driver contract. Frozen dataclasses give us cheap immutability
and equality semantics for caching and reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class AuthMethod(StrEnum):
    PASSWORD = "password"
    SSH_KEY = "ssh_key"
    API_TOKEN = "api_token"
    SNMP_V2C_COMMUNITY = "snmp_v2c_community"
    SNMP_V3 = "snmp_v3"


class DriverCapabilities(BaseModel):
    """What a driver can and cannot do. Surfaced to the UI verbatim."""

    writable: bool
    supports_commit_confirm: bool
    native_api_available: bool
    supports_snmp_read: bool
    supports_lldp: bool
    max_concurrency: int
    auth_methods: list[AuthMethod]
    web_ui_url_template: str | None = None


@dataclass(frozen=True)
class PortState:
    name: str
    admin_up: bool
    link_up: bool
    speed_mbps: int | None
    duplex: Literal["full", "half"] | None
    mac: str | None
    mtu: int | None
    untagged_vlan: int | None
    tagged_vlans: tuple[int, ...]
    description: str
    host_model: str
    bmc_ip: str
    notes: str
    services: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Neighbor:
    chassis_id: str
    port_id: str
    system_name: str | None
    system_description: str | None = None


@dataclass(frozen=True)
class MacEntry:
    """One row of the L2 forwarding (MAC address) table."""

    vlan: int | None
    mac: str
    interface: str
    type: str  # "Dynamic" / "Static" / etc.
    age: str | None = None


@dataclass(frozen=True)
class ProtocolStatus:
    """A control-plane protocol the device has configured (live, from config)."""

    name: str  # e.g. "lldp", "ospf", "spanning-tree"
    enabled: bool
    detail: str = ""  # one-line summary (e.g. "router-id 10.10.250.2 · 6 areas")
    params: tuple[tuple[str, str], ...] = ()  # key/value detail rows for expansion
    has_detail: bool = False  # operational gets available (get_protocol_detail)


@dataclass(frozen=True)
class MgmtService:
    """A management-plane service the device exposes (ssh/web/netconf/...).

    ``configured`` distinguishes a service present in the device config from a
    known service that is absent (surfaced greyed as "not configured" so an
    admin can see what could be turned on).
    """

    name: str
    enabled: bool
    port: int | None = None
    detail: str = ""
    configured: bool = True


@dataclass(frozen=True)
class VlanInfo:
    """One entry of the device's VLAN database."""

    vlan_id: int
    name: str = ""
    description: str = ""
    l3_interface: str = ""  # SVI name if the VLAN is routed (e.g. "vlan1010")
    port_count: int = 0  # access/trunk member ports referencing this VLAN


@dataclass(frozen=True)
class ProtocolTable:
    """One operational table (e.g. OSPF neighbors) — column headers + rows."""

    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ProtocolDetail:
    """Operational detail for one protocol — several named tables ("gets").

    ``error`` is set when the device couldn't be read (e.g. SSH timeout); the
    UI distinguishes that from a genuinely empty result.
    """

    slug: str
    tables: tuple[ProtocolTable, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class DeviceFacts:
    """Hardware/software facts from the device (e.g. PicOS ``show version``)."""

    model: str = ""
    os_version: str = ""
    serial: str = ""
    uptime: str = ""
    license: str = ""
    base_mac: str = ""
    released: str = ""


@dataclass(frozen=True)
class SystemInfo:
    """Live operational snapshot beyond ports: protocols, mgmt services, MAC table.

    Each section is independently optional — a driver fills what its transport
    can reach. ``mac_supported`` distinguishes "looked, table empty" from
    "this driver can't read the MAC table at all".
    """

    protocols: tuple[ProtocolStatus, ...] = ()
    services: tuple[MgmtService, ...] = ()
    mac_table: tuple[MacEntry, ...] = ()
    mac_supported: bool = False
    facts: DeviceFacts = field(default_factory=DeviceFacts)


@dataclass(frozen=True)
class ConfigDiff:
    """A rendered, not-yet-applied configuration change.

    ``metadata`` is a free-form, string-typed bag of driver-specific hints
    that travel with the diff between ``render_change`` and ``apply_change``
    (e.g. Arista session name, Pica8 pending token). Keep it small — the
    UI surfaces ``summary`` / ``commands``; metadata is internal-only.
    """

    summary: str
    raw_before: str
    raw_after: str
    commands: tuple[str, ...]
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ApplyResult:
    success: bool
    confirm_token: str | None
    confirm_deadline_at: float | None  # unix ts
    error: str | None = None


@dataclass(frozen=True)
class TestResult:
    __test__ = False  # not a pytest test class
    ok: bool
    latency_ms: float
    platform_version: str | None
    error: str | None = None


@dataclass(frozen=True)
class DiscoveryResult:
    hostname: str
    ports: tuple[PortState, ...]
    running_config: str
    services: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Credentials:
    """Opaque cred bag. Drivers interpret per their declared auth_methods.

    SSH private keys are PEM contents in-memory, never a filesystem path —
    keeps the cred vault as the single source of truth.
    """

    username: str | None = None
    password: str | None = None
    ssh_private_key: str | None = None
    api_token: str | None = None
    # Privileged-exec ("enable") secret. When set, eAPI/CLI ``enable`` is sent
    # in object form ``{"cmd": "enable", "input": <secret>}``. Never logged.
    enable_secret: str | None = None
    snmp_community: str | None = None
    # v3 fields stubbed for forward-compat
    snmp_v3_user: str | None = None
    snmp_v3_auth_proto: str | None = None
    snmp_v3_auth_key: str | None = None
    snmp_v3_priv_proto: str | None = None
    snmp_v3_priv_key: str | None = None


@dataclass(frozen=True)
class ConnectionParams:
    host: str
    port: int | None = None  # protocol default if None
    prefer_native_api: bool = True
    timeout_seconds: float = 10.0


class PortChange(BaseModel):
    """User-facing change request payload.

    VLAN IDs are validated against the 802.1Q valid range 1..4094; 0 and 4095
    are reserved and rejected at this system boundary.
    """

    untagged_vlan: int | None = Field(default=None, ge=1, le=4094)
    tagged_vlans: list[Annotated[int, Field(ge=1, le=4094)]] | None = None
    host_model: str | None = None
    bmc_ip: str | None = None
    notes: str | None = None
    description: str | None = None
