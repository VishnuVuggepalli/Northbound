"""Pydantic v2 DTOs for the ports API surface.

Live port state (driver-sourced) is merged with human metadata (DB) into a
single view. Credentials never cross this boundary.
"""

from __future__ import annotations

import ipaddress
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from northbound.services.port_state import PortStateView


class PortStateOut(BaseModel):
    """A live port plus its human-authored metadata."""

    name: str
    admin_up: bool
    link_up: bool
    speed_mbps: int | None = None
    duplex: str | None = None
    mac: str | None = None
    mtu: int | None = None
    untagged_vlan: int | None = None
    tagged_vlans: list[int] = Field(default_factory=list)
    description: str = ""
    services: dict[str, bool] = Field(default_factory=dict)
    # Human fields (DB metadata, falling back to live).
    host_model: str = ""
    bmc_ip: str = ""
    notes: str = ""
    last_human_edit_at: str | None = None
    last_human_edit_by: str | None = None

    @classmethod
    def from_view(cls, view: PortStateView) -> PortStateOut:
        p = view.live
        return cls(
            name=p.name,
            admin_up=p.admin_up,
            link_up=p.link_up,
            speed_mbps=p.speed_mbps,
            duplex=p.duplex,
            mac=p.mac,
            mtu=p.mtu,
            untagged_vlan=p.untagged_vlan,
            tagged_vlans=list(p.tagged_vlans),
            description=p.description,
            services=dict(p.services),
            host_model=view.host_model,
            bmc_ip=view.bmc_ip,
            notes=view.notes,
            last_human_edit_at=view.last_human_edit_at,
            last_human_edit_by=view.last_human_edit_by,
        )


class PortMetadataPatchIn(BaseModel):
    """Admin direct edit of port metadata (DB-only; no device write)."""

    host_model: str | None = Field(default=None, max_length=256)
    bmc_ip: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("bmc_ip")
    @classmethod
    def _bmc_ip_is_ip_address(cls, v: str | None) -> str | None:
        """Optional IPv4/IPv6 *address* (not a CIDR). Empty/None clears the
        field and is allowed; any non-empty value must parse."""
        if v:
            ipaddress.ip_address(v)  # raises ValueError → ValidationError
        return v


class PortDescriptionIn(BaseModel):
    """Admin direct edit of the port's on-device description (config write)."""

    # No CR/LF: this lands in a CLI config line on Arista/Cisco — a newline
    # would start a new command (same guard as PortChange.description).
    description: str = Field(max_length=256, pattern=r"^[^\r\n]*$")


class PortConfigIn(BaseModel):
    """Admin direct edit of on-device port tunables (config write).

    All fields optional; at least one must be set. VLAN IDs follow 802.1Q
    (1..4094). ``enabled`` maps to the device's admin shut/no-shut.
    """

    port_mode: Literal["access", "trunk"] | None = None
    untagged_vlan: Annotated[int, Field(ge=1, le=4094)] | None = None
    tagged_vlans: list[Annotated[int, Field(ge=1, le=4094)]] | None = None
    mtu: Annotated[int, Field(ge=64, le=16360)] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> PortConfigIn:
        if all(
            v is None
            for v in (self.port_mode, self.untagged_vlan, self.tagged_vlans, self.mtu, self.enabled)
        ):
            raise ValueError("at least one tunable must be set")
        return self

    @model_validator(mode="after")
    def _vlan_requires_mode(self) -> PortConfigIn:
        # A VLAN write must state the mode explicitly. Without it the driver would
        # infer access/trunk, and an untagged-only edit could silently flip a
        # trunk to access. (The frontend always sends port_mode with VLAN fields.)
        if (
            self.untagged_vlan is not None or self.tagged_vlans is not None
        ) and self.port_mode is None:
            raise ValueError("port_mode is required when setting untagged_vlan or tagged_vlans")
        return self


class AuditEntryOut(BaseModel):
    """A single audit-log row (also reused by the audit router)."""

    id: str
    user_id: str | None = None
    action: str
    target_device_id: str | None = None
    target_port: str | None = None
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None
    result: str
    created_at: str


class PortDetailOut(BaseModel):
    """Single-port detail: live state + metadata + recent audit history."""

    port: PortStateOut
    history: list[AuditEntryOut] = Field(default_factory=list)


class ConfigOut(BaseModel):
    """Running config snapshot."""

    config_text: str
    cached: bool


class MacEntryOut(BaseModel):
    vlan: int | None = None
    mac: str
    interface: str
    type: str
    age: str | None = None


class ProtocolStatusOut(BaseModel):
    name: str
    enabled: bool
    detail: str = ""
    params: list[tuple[str, str]] = Field(default_factory=list)
    has_detail: bool = False


class VlanInfoOut(BaseModel):
    vlan_id: int
    name: str = ""
    description: str = ""
    l3_interface: str = ""
    port_count: int = 0


class L3InterfaceOut(BaseModel):
    name: str
    kind: str
    ipv4: str = ""
    gateway: str = ""
    mtu: int | None = None
    enabled: bool = True
    detail: str = ""


class OspfInterfaceOut(BaseModel):
    name: str
    area: str = ""
    cost: int | None = None
    hello_interval: int | None = None
    dead_interval: int | None = None
    passive: bool = False


class ProtocolTableOut(BaseModel):
    title: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class ProtocolDetailOut(BaseModel):
    """Operational detail for one protocol — named tables from CLI gets."""

    slug: str
    tables: list[ProtocolTableOut] = Field(default_factory=list)
    error: str | None = None


class MgmtServiceOut(BaseModel):
    name: str
    enabled: bool
    port: int | None = None
    detail: str = ""
    configured: bool = True


class DeviceFactsOut(BaseModel):
    model: str = ""
    os_version: str = ""
    serial: str = ""
    uptime: str = ""
    license: str = ""
    base_mac: str = ""
    released: str = ""


class SystemInfoOut(BaseModel):
    """Live system snapshot: device facts, protocols, mgmt services, MAC table."""

    facts: DeviceFactsOut = Field(default_factory=DeviceFactsOut)
    protocols: list[ProtocolStatusOut] = Field(default_factory=list)
    services: list[MgmtServiceOut] = Field(default_factory=list)
    mac_table: list[MacEntryOut] = Field(default_factory=list)
    mac_supported: bool = False


class BackupOut(BaseModel):
    """A stored config backup row."""

    id: str
    device_id: str
    fetched_at: str
    fetched_by: str


class BackupDiffOut(BaseModel):
    """Unified diff between a stored backup and the current running config."""

    backup_id: str
    diff: str
