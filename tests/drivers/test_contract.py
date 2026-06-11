"""The driver contract suite.

Parametrized over every registered driver. Any new driver must pass this
suite or it doesn't ship. Wave A only exercises MockDriver, which proves
the harness is wired correctly.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

# Importing main triggers driver registrations.
import northbound.main  # noqa: F401
from northbound.drivers.base import Driver, NotSupported
from northbound.drivers.registry import all_platforms
from northbound.schemas.driver import (
    ApplyResult,
    ConfigDiff,
    LagChange,
    Neighbor,
    PortChange,
    PortState,
    TestResult,
)


def _all_driver_classes() -> list[type[Driver]]:
    return list(all_platforms().values())


@pytest.fixture(params=_all_driver_classes(), ids=lambda c: c.platform_id)
def driver(
    request: pytest.FixtureRequest,
    driver_factory: Callable[[type[Driver]], Driver],
) -> Driver:
    # driver_factory (conftest.py) injects mocked transports for the
    # network-backed drivers (Arista eAPI, Pica8 NETCONF) so the contract
    # suite never touches a live switch. MockDriver passes through untouched.
    return driver_factory(request.param)


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
async def test_lag_change_is_unsupported_on_every_driver(driver: Driver) -> None:
    """LAG/LACP WRITE is a DISABLED scaffold for FUTURE lab-validated work.

    No concrete driver implements ``render_lag_change`` — every one inherits the
    ABC default that raises :class:`NotSupported`. This is asserted UNCONDITIONALLY
    (even for ``writable`` drivers) so a live LAG write can never slip in without
    this test failing. See the leaf-02 trunk-VLAN incident for why an un-live-
    validated device write path is never shipped enabled.
    """
    change = LagChange(action="create", name="ae0", members=["te-1/1/1", "te-1/1/2"])
    with pytest.raises(NotSupported):
        await driver.render_lag_change(change)


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
    # A platform that advertises :confirmed-commit returns a token+deadline to
    # confirm later; one that does not (e.g. PicOS/xorplus) commits immediately
    # with neither. Both are valid — but the two fields must agree.
    assert (result.confirm_token is None) == (result.confirm_deadline_at is None)
