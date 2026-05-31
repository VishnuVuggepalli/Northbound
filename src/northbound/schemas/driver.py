"""Driver layer schemas.

Pydantic v2 models for API-facing payloads, frozen dataclasses for the
in-process driver contract. Frozen dataclasses give us cheap immutability
and equality semantics for caching and reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


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
    """User-facing change request payload."""

    untagged_vlan: int | None = None
    tagged_vlans: list[int] | None = None
    host_model: str | None = None
    bmc_ip: str | None = None
    notes: str | None = None
    description: str | None = None
