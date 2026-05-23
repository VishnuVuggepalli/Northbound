"""Driver registry behavior."""

from __future__ import annotations

from typing import ClassVar

import pytest

from northbound.drivers.base import Driver
from northbound.drivers.registry import (
    _REGISTRY,
    all_platforms,
    get_driver_class,
    register,
)
from northbound.schemas.driver import (
    AuthMethod,
    DiscoveryResult,
    DriverCapabilities,
    PortState,
    TestResult,
)


class _DummyDriver(Driver):
    """Bare-minimum Driver subclass for registry tests.

    Concrete only because pytest cannot instantiate ABCs; we never call
    these methods here.
    """

    capabilities: ClassVar[DriverCapabilities] = DriverCapabilities(
        writable=False,
        supports_commit_confirm=False,
        native_api_available=False,
        supports_snmp_read=False,
        supports_lldp=False,
        max_concurrency=1,
        auth_methods=[AuthMethod.PASSWORD],
    )
    platform_id: ClassVar[str] = "dummy-for-registry-tests"
    display_name: ClassVar[str] = "Dummy"

    async def test_credentials(self) -> TestResult:
        return TestResult(ok=True, latency_ms=0.0, platform_version=None)

    async def discover(self) -> DiscoveryResult:
        return DiscoveryResult(hostname="x", ports=(), running_config="")

    async def reachable(self) -> bool:
        return True

    async def get_ports(self) -> list[PortState]:
        return []

    async def get_running_config(self) -> str:
        return ""

    async def backup_config(self) -> str:
        return ""


@pytest.fixture(autouse=True)
def _cleanup_dummy() -> None:
    yield
    _REGISTRY.pop(_DummyDriver.platform_id, None)


def test_register_and_lookup() -> None:
    register(_DummyDriver)
    assert get_driver_class(_DummyDriver.platform_id) is _DummyDriver
    assert _DummyDriver.platform_id in all_platforms()


def test_register_duplicate_raises() -> None:
    register(_DummyDriver)
    with pytest.raises(ValueError, match="already registered"):
        register(_DummyDriver)


def test_unknown_platform_id_raises() -> None:
    with pytest.raises(KeyError):
        get_driver_class("definitely-not-a-real-platform")


def test_all_platforms_returns_defensive_copy() -> None:
    before = all_platforms()
    before["junk"] = _DummyDriver  # mutating the snapshot must not leak
    assert "junk" not in all_platforms()


def test_mock_driver_is_registered() -> None:
    # Importing northbound.main (via test_platforms_api) registers it; but
    # we also import directly here so this test stands alone.
    import northbound.drivers.mock  # noqa: F401

    assert "mock" in all_platforms()
