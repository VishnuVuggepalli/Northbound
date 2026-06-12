"""Driver layer schemas.

Pydantic v2 models for API-facing payloads, frozen dataclasses for the
in-process driver contract. Frozen dataclasses give us cheap immutability
and equality semantics for caching and reasoning.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Free text that reaches device config must never carry CR/LF: the Arista/Cisco
# renderers are Jinja CLI templates (autoescape=False), where a newline starts a
# NEW config command — i.e. the vector for an authenticated requester smuggling
# arbitrary CLI into an admin-approved apply. (lxml escapes XML text content,
# but the constraint is enforced uniformly at this DTO chokepoint.)
_NO_CRLF = r"^[^\r\n]*$"


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
    # Live interface counters (cumulative bytes). Optional — only drivers that
    # read per-port stats populate them; None means "driver exposes no counters",
    # distinct from 0 ("no traffic seen").
    rx_bytes: int | None = None
    tx_bytes: int | None = None


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
class L3Interface:
    """A non-switchport / addressed interface: management, SVI, or LAG."""

    name: str
    kind: str  # "management" | "svi" | "loopback" | "aggregated"
    ipv4: str = ""  # e.g. "10.10.250.2/16"
    gateway: str = ""
    mtu: int | None = None
    enabled: bool = True
    detail: str = ""  # free-form (e.g. LAG members)


@dataclass(frozen=True)
class OspfInterfaceInfo:
    """One OSPF-enabled interface from config (name + area + per-iface tuning)."""

    name: str
    area: str
    cost: int | None = None
    hello_interval: int | None = None
    dead_interval: int | None = None
    passive: bool = False


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
    host_model: str | None = Field(default=None, max_length=256, pattern=_NO_CRLF)
    bmc_ip: str | None = Field(default=None, max_length=64, pattern=_NO_CRLF)
    notes: str | None = Field(default=None, max_length=4000)  # DB-only, multiline OK
    description: str | None = Field(default=None, max_length=256, pattern=_NO_CRLF)
    # Device-level tunables (admin direct write). port_mode is explicit so the
    # builder no longer has to infer access/trunk from tagged-VLAN presence.
    port_mode: Literal["access", "trunk"] | None = None
    mtu: Annotated[int, Field(ge=64, le=16360)] | None = None
    enabled: bool | None = None  # maps to <disable> (disable = not enabled)

    @field_validator("bmc_ip")
    @classmethod
    def _bmc_ip_is_ip_address(cls, v: str | None) -> str | None:
        """Optional IPv4/IPv6 *address* (not a CIDR). Empty/None clears the
        field and is allowed; any non-empty value must parse."""
        if v:
            ipaddress.ip_address(v)  # raises ValueError → ValidationError
        return v


class VlanChange(BaseModel):
    """Device-level VLAN-database change (create or delete a VLAN id).

    Unlike :class:`PortChange` this targets the VLAN table, not a switchport.
    ``name`` is only meaningful for ``create``.
    """

    action: Literal["create", "delete"]
    vlan_id: int = Field(ge=1, le=4094)
    name: str | None = Field(default=None, max_length=64, pattern=_NO_CRLF)
    description: str | None = Field(default=None, max_length=255, pattern=_NO_CRLF)


class VrfChange(BaseModel):
    """Device-level VRF create/delete (`set ip vrf <name> [description]`)."""

    action: Literal["create", "delete"]
    name: str = Field(min_length=1, max_length=64, pattern=_NO_CRLF)
    description: str | None = Field(default=None, max_length=255, pattern=_NO_CRLF)


class OspfChange(BaseModel):
    """An OSPFv2 config change (`set protocols ospf ...`).

    PicOS OSPF is interface-centric: an interface declares its area, and per-
    interface knobs tune the adjacency. ``target`` selects what changes:

    - ``router-id``: set/clear the global router-id (needs ``router_id``).
    - ``interface``: add/remove an interface in OSPF + tune it (needs ``interface``;
      ``set`` requires ``area``). Optional cost / hello / dead / passive.

    ``action="delete"`` removes the targeted node (the whole interface from OSPF,
    or the router-id). redistribute / area-type targets are deliberately not
    modelled yet (their xorplus XML isn't grounded — routing config, no guessing).
    """

    action: Literal["set", "delete"]
    target: Literal["router-id", "interface"]
    router_id: str | None = Field(default=None, max_length=15)
    interface: str | None = Field(default=None, max_length=64, pattern=_NO_CRLF)
    area: str | None = Field(default=None, max_length=15)  # dotted (0.0.0.0) or int
    cost: int | None = Field(default=None, ge=1, le=65535)
    hello_interval: int | None = Field(default=None, ge=1, le=65535)
    dead_interval: int | None = Field(default=None, ge=1, le=65535)
    passive: bool | None = None

    @field_validator("router_id")
    @classmethod
    def _router_id_is_dotted_quad(cls, v: str | None) -> str | None:
        """Router-id is a 32-bit dotted quad; reject free text at file time."""
        if v is not None:
            ipaddress.IPv4Address(v)  # raises ValueError → ValidationError
        return v

    @field_validator("area")
    @classmethod
    def _area_is_dotted_or_int(cls, v: str | None) -> str | None:
        if v is not None and not v.isdigit():
            ipaddress.IPv4Address(v)
        return v

    @model_validator(mode="after")
    def _check(self) -> OspfChange:
        if self.target == "router-id" and self.action == "set" and not self.router_id:
            raise ValueError("router-id set requires router_id")
        if self.target == "interface":
            if not self.interface:
                raise ValueError("interface target requires interface")
            if self.action == "set" and not self.area:
                raise ValueError("adding an OSPF interface requires area")
        return self


class LagChange(BaseModel):
    """A link-aggregation (LAG / LACP) change — DISABLED write scaffold.

    SAFETY: there is intentionally NO concrete-driver implementation of
    ``render_lag_change``; every driver inherits the ABC default that raises
    :class:`~northbound.drivers.base.NotSupported`. This DTO exists only so a
    FUTURE, lab-validated LAG write inherits hardened input validation — it is
    NOT wired to any apply branch or API endpoint today.

    Why so cautious: a Northbound trunk-VLAN write that was authored from docs
    and never live-validated corrupted a production Pica8 switch (leaf-02). A
    LAG write touches bond membership + LACP on a live fabric uplink — strictly
    more dangerous — so it ships disabled until validated on a lab device.

    - ``name`` is the aggregate interface (``ae0`` on PicOS, ``Po1`` on Arista/Cisco).
    - ``members`` are the physical member ports; required for ``create``.
    - ``lacp_mode`` / ``lacp_rate`` are optional LACP knobs.
    """

    action: Literal["create", "delete"]
    name: str = Field(min_length=1, max_length=64, pattern=_NO_CRLF)
    members: tuple[Annotated[str, Field(min_length=1, max_length=64, pattern=_NO_CRLF)], ...] = ()
    lacp_mode: Literal["active", "passive"] | None = None
    lacp_rate: Literal["fast", "slow"] | None = None
    system_priority: int | None = Field(default=None, ge=0, le=65535)

    @model_validator(mode="after")
    def _check(self) -> LagChange:
        if self.action == "create" and not self.members:
            raise ValueError("create requires at least one member port")
        return self


class L3Change(BaseModel):
    """A routed-interface change: create/delete an SVI (VLAN interface) or a
    loopback, with an optional IPv4 address.

    - ``svi``: ``vlan_id`` is required; the interface name is ``vlan<id>``.
    - ``loopback``: ``name`` is required (e.g. ``lo0``).
    - ``create`` requires ``ipv4`` (CIDR, e.g. ``10.0.0.1/24``); ``delete`` removes
      the whole interface and ignores ``ipv4``.
    """

    action: Literal["create", "delete"]
    kind: Literal["svi", "loopback"]
    name: str | None = Field(default=None, max_length=64, pattern=_NO_CRLF)
    vlan_id: int | None = Field(default=None, ge=1, le=4094)
    ipv4: str | None = Field(default=None, max_length=43)  # IPv4 or IPv6 CIDR
    mtu: int | None = Field(default=None, ge=64, le=16360)
    enabled: bool | None = None  # maps to <disable> (disable = not enabled)
    dhcp: bool | None = None
    vrf: str | None = Field(default=None, max_length=64, pattern=_NO_CRLF)

    @field_validator("ipv4")
    @classmethod
    def _ipv4_is_cidr_interface(cls, v: str | None) -> str | None:
        """Must parse as an address-with-prefix (v4 or v6) — fail at file time,
        not at apply time on the device."""
        if v is not None:
            ipaddress.ip_interface(v)  # raises ValueError → ValidationError
        return v

    @model_validator(mode="after")
    def _check(self) -> L3Change:
        if self.kind == "svi" and self.vlan_id is None:
            raise ValueError("svi requires vlan_id")
        if self.kind == "loopback" and not self.name:
            raise ValueError("loopback requires name")
        if self.action == "create" and not self.ipv4:
            raise ValueError("create requires ipv4 (CIDR)")
        return self

    @property
    def iface_name(self) -> str:
        """Canonical interface name: ``vlan<id>`` for an SVI, else ``name``."""
        return f"vlan{self.vlan_id}" if self.kind == "svi" else (self.name or "")
