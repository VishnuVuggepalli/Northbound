"""Pydantic v2 DTOs for the devices / onboarding API surface.

These are the only shapes that cross the HTTP boundary for devices.
``encrypted_credentials`` and raw credential values are deliberately absent
from every response model so they can never be serialised out of the service.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from northbound.models.enums import DeviceRole, Environment
from northbound.schemas.driver import Credentials, DriverCapabilities


class CredentialsIn(BaseModel):
    """Inbound credential bag. All fields optional; the driver interprets
    them per its declared ``auth_methods``. Never echoed back in a response."""

    username: str | None = Field(default=None, max_length=128)
    password: str | None = None
    ssh_private_key: str | None = None
    api_token: str | None = None
    snmp_community: str | None = None
    enable_secret: str | None = None

    def to_credentials(self) -> Credentials:
        """Build the in-process :class:`Credentials` value object."""
        return Credentials(
            username=self.username,
            password=self.password,
            ssh_private_key=self.ssh_private_key,
            api_token=self.api_token,
            snmp_community=self.snmp_community,
            enable_secret=self.enable_secret,
        )


class ConnectionTestIn(BaseModel):
    """Body of ``POST /api/devices/test-connection`` — transient, no persist."""

    platform_id: str = Field(min_length=1, max_length=64)
    mgmt_ip: str = Field(min_length=1, max_length=64)
    port: int | None = Field(default=None, ge=1, le=65535)
    prefer_native_api: bool = True
    credentials: CredentialsIn = Field(default_factory=CredentialsIn)


class DiscoverIn(ConnectionTestIn):
    """Body of ``POST /api/devices/discover`` — same shape as test-connection."""


class DeviceCreateIn(BaseModel):
    """Body of ``POST /api/devices`` — atomic onboard."""

    name: str = Field(min_length=1, max_length=128)
    environment: Environment
    role: DeviceRole
    platform_id: str = Field(min_length=1, max_length=64)
    mgmt_ip: str = Field(min_length=1, max_length=64)
    port: int | None = Field(default=None, ge=1, le=65535)
    ssh_user: str | None = Field(default=None, max_length=128)
    prefer_native_api: bool = True
    credentials: CredentialsIn = Field(default_factory=CredentialsIn)


class CredentialsRotateIn(BaseModel):
    """Body of ``PATCH /api/devices/{id}/credentials``."""

    credentials: CredentialsIn


class TestConnectionOut(BaseModel):
    """Result of a live credential probe. Mirrors the driver TestResult."""

    ok: bool
    latency_ms: float
    platform_version: str | None = None
    error: str | None = None


class PortOut(BaseModel):
    """A discovered port, with parsed human fields surfaced for preview."""

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
    host_model: str = ""
    bmc_ip: str = ""
    notes: str = ""


class DiscoverOut(BaseModel):
    """Onboarding preview — never persisted."""

    hostname: str
    ports: list[PortOut] = Field(default_factory=list)
    running_config: str = ""
    services: dict[str, bool] = Field(default_factory=dict)


class DeviceOut(BaseModel):
    """Public view of a device. NEVER includes credentials of any kind."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    environment: Environment
    role: DeviceRole
    platform: str
    mgmt_ip: str
    ssh_user: str | None = None
    prefer_native_api: bool
    capabilities: DriverCapabilities | None = None
    writable: bool = False
    reachable: bool | None = None
