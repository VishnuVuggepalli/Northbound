"""Reachability map + poll-job tests.

The poll job is driven directly (no real APScheduler timers). A device whose
driver raises is recorded as unreachable, never propagated. Map reads return
both the boolean and the ``checked_at`` instant.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northbound.drivers import registry
from northbound.drivers.base import ReachabilityError
from northbound.models.device import Device
from northbound.models.enums import DeviceRole, Environment
from northbound.schemas.driver import (
    AuthMethod,
    ConnectionParams,
    Credentials,
    DiscoveryResult,
    DriverCapabilities,
    PortState,
    TestResult,
)
from northbound.services import reachability, scheduler
from northbound.services.scheduler import poll_reachability

_CAPS = DriverCapabilities(
    writable=True,
    supports_commit_confirm=False,
    native_api_available=True,
    supports_snmp_read=False,
    supports_lldp=False,
    max_concurrency=5,
    auth_methods=[AuthMethod.PASSWORD],
)


class _UnreachableDriver:
    """Minimal driver stub whose ``reachable`` raises (network down)."""

    capabilities = _CAPS
    platform_id = "unreachable_test"
    display_name = "Unreachable Test"

    def __init__(self, conn: ConnectionParams, creds: Credentials) -> None:
        self._conn = conn
        self._creds = creds

    async def test_credentials(self) -> TestResult:
        return TestResult(ok=False, latency_ms=0.0, platform_version=None)

    async def discover(self) -> DiscoveryResult:
        return DiscoveryResult(hostname="h", ports=(), running_config="")

    async def reachable(self) -> bool:
        raise ReachabilityError("network down")

    async def get_ports(self) -> list[PortState]:
        return []

    async def get_running_config(self) -> str:
        return ""

    async def backup_config(self) -> str:
        return ""


@pytest.fixture(autouse=True)
def _reset_reachability() -> Iterator[None]:
    reachability.clear()
    yield
    reachability.clear()


@pytest_asyncio.fixture
async def patched_factory(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    """Point poll_reachability's own-session factory at the test engine."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler, "async_session_factory", factory)
    yield


@pytest.fixture
def _register_unreachable() -> Iterator[None]:
    registry._REGISTRY["unreachable_test"] = _UnreachableDriver  # type: ignore[assignment]
    try:
        yield
    finally:
        registry._REGISTRY.pop("unreachable_test", None)


def test_record_and_read_roundtrip() -> None:
    """record() then get() returns the boolean and checked_at."""
    now = dt.datetime(2026, 5, 30, 12, 0, tzinfo=dt.UTC)
    reachability.record("dev-1", reachable=True, checked_at=now)

    status = reachability.get("dev-1")
    assert status is not None
    assert status.reachable is True
    assert status.checked_at == now
    assert reachability.is_reachable("dev-1") is True


def test_unpolled_device_is_unknown() -> None:
    """A device never polled reports None (not False) — 'unknown'."""
    assert reachability.get("never") is None
    assert reachability.is_reachable("never") is None


async def test_poll_updates_map_for_reachable_device(
    db_session: AsyncSession,
    mock_device: Device,
    patched_factory: None,
) -> None:
    """poll_reachability marks a healthy mock device reachable + stamps time."""
    await db_session.commit()  # make the device visible to the job's own session
    await poll_reachability()

    status = reachability.get(mock_device.id)
    assert status is not None
    assert status.reachable is True
    assert status.checked_at.tzinfo is not None


async def test_poll_marks_unreachable_without_raising(
    db_session: AsyncSession,
    _register_unreachable: None,
    patched_factory: None,
) -> None:
    """A driver that raises in reachable() → reachable=False, no exception."""
    device = Device(
        name="down-box",
        environment=Environment.LAB,
        platform="unreachable_test",
        role=DeviceRole.LEAF,
        mgmt_ip="10.0.0.9",
        prefer_native_api=True,
        encrypted_credentials=None,
    )
    db_session.add(device)
    await db_session.commit()

    # Must NOT raise even though the driver's reachable() throws.
    await poll_reachability()

    status = reachability.get(device.id)
    assert status is not None
    assert status.reachable is False
