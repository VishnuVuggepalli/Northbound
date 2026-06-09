"""Tests for the port_state service: cache, metadata merge, fingerprint."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.drivers import registry
from northbound.drivers.base import Driver
from northbound.models.device import Device
from northbound.models.enums import DeviceRole
from northbound.models.port_metadata import PortMetadata
from northbound.schemas.driver import (
    AuthMethod,
    Credentials,
    DiscoveryResult,
    DriverCapabilities,
    PortState,
    TestResult,
)
from northbound.services import port_state
from northbound.services.credvault import FernetCredVault, serialize_credentials

# Module-level call counter the counting driver increments.
_CALLS = {"get_ports": 0}


def _port(name: str, vlan: int | None, tagged: tuple[int, ...] = ()) -> PortState:
    return PortState(
        name=name,
        admin_up=True,
        link_up=True,
        speed_mbps=1000,
        duplex="full",
        mac=None,
        mtu=1500,
        untagged_vlan=vlan,
        tagged_vlans=tagged,
        description="",
        host_model="",
        bmc_ip="",
        notes="",
    )


class _CountingDriver(Driver):
    platform_id = "counting"
    display_name = "Counting (test)"
    capabilities = DriverCapabilities(
        writable=True,
        supports_commit_confirm=True,
        native_api_available=True,
        supports_snmp_read=False,
        supports_lldp=False,
        max_concurrency=5,
        auth_methods=[AuthMethod.PASSWORD],
    )

    _ports: tuple[PortState, ...] = (_port("Eth1", 1), _port("Eth2", 100, (200, 300)))

    async def test_credentials(self) -> TestResult:
        return TestResult(ok=True, latency_ms=1.0, platform_version="x")

    async def discover(self) -> DiscoveryResult:
        return DiscoveryResult(hostname="h", ports=self._ports, running_config="")

    async def reachable(self) -> bool:
        return True

    async def get_ports(self) -> list[PortState]:
        _CALLS["get_ports"] += 1
        return list(type(self)._ports)

    async def get_running_config(self) -> str:
        return ""

    async def backup_config(self) -> str:
        return ""


@pytest.fixture(autouse=True)
def _register_counting() -> Iterator[None]:
    _CALLS["get_ports"] = 0
    registry.register(_CountingDriver)
    try:
        yield
    finally:
        registry._REGISTRY.pop("counting", None)
        # restore original port set
        _CountingDriver._ports = (_port("Eth1", 1), _port("Eth2", 100, (200, 300)))


@pytest_asyncio.fixture
async def counting_device(db_session: AsyncSession) -> Device:
    vault = FernetCredVault.from_settings()
    device = Device(
        name="lab-counting-1",
        environment="lab",
        platform="counting",
        role=DeviceRole.LEAF,
        mgmt_ip="10.0.0.9",
        prefer_native_api=True,
        encrypted_credentials=serialize_credentials(Credentials(username="u"), vault),
    )
    db_session.add(device)
    await db_session.flush()
    return device


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_driver_call(
    db_session: AsyncSession, counting_device: Device
) -> None:
    await port_state.get_ports(db_session, counting_device)
    await port_state.get_ports(db_session, counting_device)
    assert _CALLS["get_ports"] == 1


@pytest.mark.asyncio
async def test_refresh_forces_driver_call(
    db_session: AsyncSession, counting_device: Device
) -> None:
    await port_state.get_ports(db_session, counting_device)
    await port_state.get_ports(db_session, counting_device, refresh=True)
    assert _CALLS["get_ports"] == 2


@pytest.mark.asyncio
async def test_metadata_merged_onto_live(db_session: AsyncSession, counting_device: Device) -> None:
    db_session.add(
        PortMetadata(
            device_id=counting_device.id,
            port_name="Eth1",
            host_model="Dell R740",
            bmc_ip="10.0.0.55",
            notes="rack 3",
        )
    )
    await db_session.flush()
    views = await port_state.get_ports(db_session, counting_device)
    eth1 = next(v for v in views if v.live.name == "Eth1")
    assert eth1.host_model == "Dell R740"
    assert eth1.bmc_ip == "10.0.0.55"
    assert eth1.notes == "rack 3"


@pytest.mark.asyncio
async def test_fingerprint_stable_and_changes_with_vlan(
    db_session: AsyncSession, counting_device: Device
) -> None:
    fp1 = await port_state.current_fingerprint(counting_device, refresh=True)
    fp2 = await port_state.current_fingerprint(counting_device, refresh=True)
    assert fp1 == fp2  # stable for same state

    # Mutate the driver's port VLANs → fingerprint must change.
    _CountingDriver._ports = (_port("Eth1", 999), _port("Eth2", 100, (200, 300)))
    fp3 = await port_state.current_fingerprint(counting_device, refresh=True)
    assert fp3 != fp1


def test_fingerprint_order_independent() -> None:
    a = port_state.device_state_fingerprint([_port("Eth1", 1), _port("Eth2", 2)])
    b = port_state.device_state_fingerprint([_port("Eth2", 2), _port("Eth1", 1)])
    assert a == b


def test_fingerprint_scoped_to_one_port() -> None:
    """With ``port_name`` set, only that port's VLAN state feeds the hash, so an
    unrelated port changing does NOT change the scoped fingerprint."""
    base = [_port("Eth1", 10, (100,)), _port("Eth2", 20, (200,))]
    other_moved = [_port("Eth1", 10, (100,)), _port("Eth2", 999, (200,))]

    # Whole-device hash is sensitive to ANY port (status quo).
    assert port_state.device_state_fingerprint(base) != port_state.device_state_fingerprint(
        other_moved
    )

    # Scoped to Eth1: unrelated Eth2 change is invisible.
    scoped = port_state.device_state_fingerprint(base, port_name="Eth1")
    assert scoped == port_state.device_state_fingerprint(other_moved, port_name="Eth1")

    # But changing Eth1 itself still drifts the scoped hash.
    eth1_moved = [_port("Eth1", 11, (100,)), _port("Eth2", 20, (200,))]
    assert scoped != port_state.device_state_fingerprint(eth1_moved, port_name="Eth1")

    # A port not present hashes the empty set (stable, distinct).
    assert port_state.device_state_fingerprint(base, port_name="Nope") == (
        port_state.device_state_fingerprint([], port_name="Nope")
    )
