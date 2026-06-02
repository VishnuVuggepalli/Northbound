"""Pydantic v2 DTOs for the ports API surface.

Live port state (driver-sourced) is merged with human metadata (DB) into a
single view. Credentials never cross this boundary.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

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
    notes: str | None = None


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


class MgmtServiceOut(BaseModel):
    name: str
    enabled: bool
    port: int | None = None
    detail: str = ""


class SystemInfoOut(BaseModel):
    """Live system snapshot: protocols, mgmt services, MAC table."""

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
