"""The driver contract suite.

Parametrized over every registered driver. Any new driver must pass this
suite or it doesn't ship. Wave A only exercises MockDriver, which proves
the harness is wired correctly.
"""

from __future__ import annotations

import pytest

# Importing main triggers driver registrations.
import northbound.main  # noqa: F401
from northbound.drivers.base import Driver, NotSupported
from northbound.drivers.registry import all_platforms
from northbound.schemas.driver import (
    ApplyResult,
    ConfigDiff,
    ConnectionParams,
    Credentials,
    Neighbor,
    PortChange,
    PortState,
    TestResult,
)


def _all_driver_classes() -> list[type[Driver]]:
    return list(all_platforms().values())


def _instantiate(cls: type[Driver]) -> Driver:
    return cls(
        ConnectionParams(host="127.0.0.1"),
        Credentials(username="x", password="y"),
    )


@pytest.fixture(params=_all_driver_classes(), ids=lambda c: c.platform_id)
def driver(request: pytest.FixtureRequest) -> Driver:
    return _instantiate(request.param)


@pytest.mark.asyncio
async def test_capabilities_consistent(driver: Driver) -> None:
    caps = driver.capabilities
    if caps.writable:
        return
    diff = ConfigDiff(summary="x", raw_before="", raw_after="", commands=())
    with pytest.raises(NotSupported):
        await driver.render_change("Ethernet1", PortChange())
    with pytest.raises(NotSupported):
        await driver.apply_change(diff)
    with pytest.raises(NotSupported):
        await driver.confirm("token")
    with pytest.raises(NotSupported):
        await driver.revert("token")


@pytest.mark.asyncio
async def test_get_ports_returns_PortState_list(driver: Driver) -> None:
    ports = await driver.get_ports()
    assert isinstance(ports, list)
    for p in ports:
        assert isinstance(p, PortState)


@pytest.mark.asyncio
async def test_get_neighbors_returns_list(driver: Driver) -> None:
    neighbors = await driver.get_neighbors()
    assert isinstance(neighbors, list)
    for n in neighbors:
        assert isinstance(n, Neighbor)


@pytest.mark.asyncio
async def test_test_credentials_returns_TestResult(driver: Driver) -> None:
    result = await driver.test_credentials()
    assert isinstance(result, TestResult)
    assert isinstance(result.ok, bool)
    assert isinstance(result.latency_ms, float)


@pytest.mark.asyncio
async def test_backup_config_returns_non_empty_string(driver: Driver) -> None:
    backup = await driver.backup_config()
    assert isinstance(backup, str)
    assert backup, "backup_config returned empty string"


@pytest.mark.asyncio
async def test_writable_driver_can_render_and_apply(driver: Driver) -> None:
    if not driver.capabilities.writable:
        return
    diff = await driver.render_change(
        "Ethernet1",
        PortChange(description="contract-test", untagged_vlan=10),
    )
    assert isinstance(diff, ConfigDiff)
    assert diff.commands, "render_change produced no commands"

    result = await driver.apply_change(diff, confirm_seconds=30)
    assert isinstance(result, ApplyResult)
    assert result.success is True
    assert result.confirm_token is not None
    assert result.confirm_deadline_at is not None
