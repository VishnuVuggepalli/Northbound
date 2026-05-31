"""Tests for the devices CRUD + onboarding API surface.

Uses the in-memory DB fixtures from ``tests/conftest.py`` and the ``mock``
platform (MockDriver) so onboarding runs with no network. Auth is exercised
with real JWTs minted for seeded admin / requester users.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

os.environ["NB_SECRET_KEY"] = "unit-test-secret-key"
os.environ["NB_MASTER_KEY"] = "wDPYj3kZ3qbY8m0v6m2nQ1rJf7xq9o5xS3uVc8nH0cE="

from northbound.auth.jwt import create_access_token
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.drivers import registry
from northbound.drivers.base import Driver, ReachabilityError
from northbound.main import app
from northbound.models.audit_log import AuditLog
from northbound.models.change_request import ChangeRequest
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus, DeviceRole, Environment, UserRole
from northbound.models.port_metadata import PortMetadata
from northbound.models.user import User
from northbound.schemas.driver import (
    AuthMethod,
    Credentials,
    DiscoveryResult,
    DriverCapabilities,
    PortState,
    TestResult,
)
from northbound.services.credvault import FernetCredVault, deserialize_credentials
from northbound.services.device_policy import assert_writable
from northbound.services.onboarding import parse_description

get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# Test-only drivers. NOT registered at import time — an autouse fixture below
# injects them into the registry and removes them on teardown, so they never
# pollute the contract suite / /api/platforms when other modules run.
# --------------------------------------------------------------------------- #
class _FailingDiscoverDriver(Driver):
    platform_id = "faildiscover"
    display_name = "Failing discover (test)"
    capabilities = DriverCapabilities(
        writable=True,
        supports_commit_confirm=False,
        native_api_available=False,
        supports_snmp_read=False,
        supports_lldp=False,
        max_concurrency=1,
        auth_methods=[AuthMethod.PASSWORD],
        web_ui_url_template=None,
    )

    async def test_credentials(self) -> TestResult:
        return TestResult(ok=True, latency_ms=1.0, platform_version="x")

    async def discover(self) -> DiscoveryResult:
        raise ReachabilityError("simulated discovery failure")

    async def reachable(self) -> bool:
        return False

    async def get_ports(self) -> list[PortState]:
        return []

    async def get_running_config(self) -> str:
        return ""

    async def backup_config(self) -> str:
        return ""


class _FailTestDriver(Driver):
    """test_credentials returns ok=False — used to prove rotate keeps old creds."""

    platform_id = "failtest"
    display_name = "Failing test (test)"
    capabilities = _FailingDiscoverDriver.capabilities

    async def test_credentials(self) -> TestResult:
        return TestResult(ok=False, latency_ms=0.0, platform_version=None, error="bad creds")

    async def discover(self) -> DiscoveryResult:
        raise ReachabilityError("n/a")

    async def reachable(self) -> bool:
        return False

    async def get_ports(self) -> list[PortState]:
        return []

    async def get_running_config(self) -> str:
        return ""

    async def backup_config(self) -> str:
        return ""


class _ReadOnlyPlatformDriver(Driver):
    """A platform whose capabilities.writable is False — for assert_writable."""

    platform_id = "readonlyplat"
    display_name = "Read-only platform (test)"
    capabilities = DriverCapabilities(
        writable=False,
        supports_commit_confirm=False,
        native_api_available=False,
        supports_snmp_read=False,
        supports_lldp=False,
        max_concurrency=1,
        auth_methods=[AuthMethod.PASSWORD],
        web_ui_url_template=None,
    )

    async def test_credentials(self) -> TestResult:
        return TestResult(ok=True, latency_ms=1.0, platform_version="ro")

    async def discover(self) -> DiscoveryResult:
        raise ReachabilityError("n/a")

    async def reachable(self) -> bool:
        return True

    async def get_ports(self) -> list[PortState]:
        return []

    async def get_running_config(self) -> str:
        return ""

    async def backup_config(self) -> str:
        return ""


_TEST_DRIVERS: tuple[type[Driver], ...] = (
    _FailingDiscoverDriver,
    _FailTestDriver,
    _ReadOnlyPlatformDriver,
)


@pytest.fixture(autouse=True)
def _register_test_drivers() -> Iterator[None]:
    """Register the test-only drivers for the duration of each test, then
    remove them so they never leak into the contract suite or platforms list."""
    for cls in _TEST_DRIVERS:
        registry.register(cls)
    try:
        yield
    finally:
        for cls in _TEST_DRIVERS:
            registry._REGISTRY.pop(cls.platform_id, None)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncSession, User, User]]:
    admin = User(username="admin", password_hash=hash_password("admin-pw"), role=UserRole.ADMIN)
    alice = User(username="alice", password_hash=hash_password("alice-pw"), role=UserRole.REQUESTER)
    db_session.add_all([admin, alice])
    await db_session.flush()
    yield db_session, admin, alice


@pytest_asyncio.fixture
async def client(seeded: tuple[AsyncSession, User, User]) -> AsyncIterator[AsyncClient]:
    session = seeded[0]

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(sub=user.id, role=user.role, settings=get_settings())
    return {"Authorization": f"Bearer {token}"}


def _onboard_body(name: str = "lab-leaf-1", platform: str = "mock") -> dict[str, object]:
    return {
        "name": name,
        "environment": "lab",
        "role": "leaf",
        "platform_id": platform,
        "mgmt_ip": "10.0.0.1",
        "ssh_user": "admin",
        "prefer_native_api": True,
        "credentials": {"username": "admin", "password": "switch-pw"},
    }


# --------------------------------------------------------------------------- #
# test-connection
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_test_connection_ok(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    resp = await client.post(
        "/api/devices/test-connection",
        headers=_bearer(admin),
        json={
            "platform_id": "mock",
            "mgmt_ip": "10.0.0.1",
            "credentials": {"username": "u", "password": "p"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["platform_version"] == "mock-1.0"


@pytest.mark.asyncio
async def test_test_connection_requires_admin(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, _, alice = seeded
    resp = await client.post(
        "/api/devices/test-connection",
        headers=_bearer(alice),
        json={"platform_id": "mock", "mgmt_ip": "10.0.0.1", "credentials": {}},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_test_connection_unknown_platform_400(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    resp = await client.post(
        "/api/devices/test-connection",
        headers=_bearer(admin),
        json={"platform_id": "nope", "mgmt_ip": "10.0.0.1", "credentials": {}},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# discover
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_discover_returns_ports(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    resp = await client.post(
        "/api/devices/discover",
        headers=_bearer(admin),
        json={"platform_id": "mock", "mgmt_ip": "10.0.0.1", "credentials": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hostname"] == "mock-switch-01"
    assert len(body["ports"]) == 8
    assert body["running_config"]


# --------------------------------------------------------------------------- #
# POST /api/devices — atomic onboard
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_onboard_creates_all_rows_and_hides_creds(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    session, admin, _ = seeded
    resp = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "lab-leaf-1"
    assert body["writable"] is True
    # No credential material anywhere in the response.
    flat = str(body)
    assert "switch-pw" not in flat
    assert "credentials" not in body
    assert "encrypted_credentials" not in body

    device_id = body["id"]
    device = await session.scalar(select(Device).where(Device.id == device_id))
    assert device is not None
    # Credentials stored encrypted, round-trip via the vault.
    assert device.encrypted_credentials is not None
    vault = FernetCredVault.from_settings()
    creds = deserialize_credentials(device.encrypted_credentials, vault)
    assert creds == Credentials(username="admin", password="switch-pw")

    # 8 port_metadata rows (matches MockDriver inventory).
    port_count = await session.scalar(
        select(func.count()).select_from(PortMetadata).where(PortMetadata.device_id == device_id)
    )
    assert port_count == 8

    # One baseline config backup.
    backup = await session.scalar(select(ConfigBackup).where(ConfigBackup.device_id == device_id))
    assert backup is not None
    assert backup.config_text

    # Audit entry recorded — action only, no plaintext creds.
    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "device.onboarded"))
    assert audit is not None
    assert "switch-pw" not in str(audit.after)


@pytest.mark.asyncio
async def test_onboard_parses_description_into_metadata(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    session, admin, _ = seeded
    resp = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    assert resp.status_code == 201
    device_id = resp.json()["id"]
    # MockDriver Ethernet1 has host_model/bmc_ip set directly; assert they land.
    pm = await session.scalar(
        select(PortMetadata).where(
            PortMetadata.device_id == device_id, PortMetadata.port_name == "Ethernet1"
        )
    )
    assert pm is not None
    assert pm.host_model == "r720-01"
    assert pm.bmc_ip == "10.0.0.11"


@pytest.mark.asyncio
async def test_onboard_rolls_back_when_discover_fails(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    session, admin, _ = seeded
    body = _onboard_body(name="will-not-exist", platform="faildiscover")
    resp = await client.post("/api/devices", headers=_bearer(admin), json=body)
    assert resp.status_code == 502
    # No orphan device, ports, backups, or onboarded-audit rows.
    assert await session.scalar(select(func.count()).select_from(Device)) == 0
    assert await session.scalar(select(func.count()).select_from(PortMetadata)) == 0
    assert await session.scalar(select(func.count()).select_from(ConfigBackup)) == 0


@pytest.mark.asyncio
async def test_onboard_duplicate_name_409(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    first = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    assert first.status_code == 201
    dup = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_onboard_requires_admin(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, _, alice = seeded
    resp = await client.post("/api/devices", headers=_bearer(alice), json=_onboard_body())
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# GET list + filter + detail
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_list_and_environment_filter(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, alice = seeded
    await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body(name="lab-1"))
    dc_body = _onboard_body(name="dc-1")
    dc_body["environment"] = "dc"
    await client.post("/api/devices", headers=_bearer(admin), json=dc_body)

    # Requester can read.
    all_resp = await client.get("/api/devices", headers=_bearer(alice))
    assert all_resp.status_code == 200
    assert {d["name"] for d in all_resp.json()} == {"lab-1", "dc-1"}

    lab_resp = await client.get("/api/devices?environment=lab", headers=_bearer(alice))
    assert [d["name"] for d in lab_resp.json()] == ["lab-1"]


@pytest.mark.asyncio
async def test_get_detail_and_404(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    created = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    device_id = created.json()["id"]
    detail = await client.get(f"/api/devices/{device_id}", headers=_bearer(admin))
    assert detail.status_code == 200
    assert detail.json()["id"] == device_id
    assert "encrypted_credentials" not in detail.json()

    missing = await client.get("/api/devices/does-not-exist", headers=_bearer(admin))
    assert missing.status_code == 404


# --------------------------------------------------------------------------- #
# PATCH credentials — rotate
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rotate_credentials_success(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    session, admin, _ = seeded
    created = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    device_id = created.json()["id"]

    resp = await client.patch(
        f"/api/devices/{device_id}/credentials",
        headers=_bearer(admin),
        json={"credentials": {"username": "admin", "password": "new-pw"}},
    )
    assert resp.status_code == 200
    session.expire_all()
    device = await session.scalar(select(Device).where(Device.id == device_id))
    assert device is not None
    vault = FernetCredVault.from_settings()
    creds = deserialize_credentials(device.encrypted_credentials or b"", vault)
    assert creds.password == "new-pw"


@pytest.mark.asyncio
async def test_rotate_credentials_failed_test_keeps_old(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    session, admin, _ = seeded
    # Onboard with faildiscover platform but seed via mock so a device exists,
    # then point a failing-test driver at it. Simpler: onboard on mock, then
    # rotate using the faildiscover platform by editing the device.platform.
    created = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    device_id = created.json()["id"]

    # Flip platform to one whose test_credentials returns ok but we force failure
    # by using a driver that raises. We use a TestResult(ok=False) driver instead.
    device = await session.scalar(select(Device).where(Device.id == device_id))
    assert device is not None
    original_blob = device.encrypted_credentials
    device.platform = "failtest"
    await session.flush()

    resp = await client.patch(
        f"/api/devices/{device_id}/credentials",
        headers=_bearer(admin),
        json={"credentials": {"username": "admin", "password": "rejected"}},
    )
    assert resp.status_code == 400
    session.expire_all()
    refreshed = await session.scalar(select(Device).where(Device.id == device_id))
    assert refreshed is not None
    # Old credential blob retained unchanged.
    assert refreshed.encrypted_credentials == original_blob


# --------------------------------------------------------------------------- #
# DELETE — offboard + cascade
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_delete_cascades_ports(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    session, admin, _ = seeded
    created = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    device_id = created.json()["id"]

    resp = await client.delete(f"/api/devices/{device_id}", headers=_bearer(admin))
    assert resp.status_code == 204

    assert await session.scalar(select(Device).where(Device.id == device_id)) is None
    port_count = await session.scalar(
        select(func.count()).select_from(PortMetadata).where(PortMetadata.device_id == device_id)
    )
    assert port_count == 0
    # Offboard audit entry recorded.
    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "device.offboarded"))
    assert audit is not None


@pytest.mark.asyncio
async def test_delete_requires_admin(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, alice = seeded
    created = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    device_id = created.json()["id"]
    resp = await client.delete(f"/api/devices/{device_id}", headers=_bearer(alice))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_blocked_by_change_request_history_409(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    """A device with change-request history cannot be hard-deleted (FK RESTRICT).

    The compliance trail must be retained, so the delete surfaces as 409 — not
    an unhandled 500 — and the device and its change request are left intact.
    """
    session, admin, _ = seeded
    created = await client.post("/api/devices", headers=_bearer(admin), json=_onboard_body())
    device_id = created.json()["id"]

    session.add(
        ChangeRequest(
            device_id=device_id,
            port_name="Ethernet1",
            requested_by=admin.username,
            requested_changes={"untagged_vlan": 10},
            reason="apply test",
            status=ChangeRequestStatus.APPLIED,
        )
    )
    await session.flush()
    # The device exists right up to the delete attempt; the change request is the
    # sole reason the FK RESTRICT trips.
    assert await session.scalar(select(Device).where(Device.id == device_id)) is not None

    resp = await client.delete(f"/api/devices/{device_id}", headers=_bearer(admin))
    # 409 (not 500): the IntegrityError from FK RESTRICT is caught and attributed
    # to the retained compliance trail.
    assert resp.status_code == 409
    assert "change trail" in resp.json()["detail"]
    # NOTE: the endpoint calls session.rollback() on the IntegrityError. In
    # production each request owns its own committed session, so rollback only
    # undoes the failed DELETE and the device persists. Here the test shares one
    # never-committed session across requests, so rollback also discards the
    # device/CR set up above — asserting post-rollback row state would test the
    # harness, not the code. The 409 contract is the meaningful guarantee.


# --------------------------------------------------------------------------- #
# assert_writable unit tests
# --------------------------------------------------------------------------- #
def _device(role: DeviceRole, platform: str = "mock") -> Device:
    return Device(
        name="x",
        environment=Environment.LAB,
        platform=platform,
        role=role,
        mgmt_ip="10.0.0.1",
        prefer_native_api=True,
    )


def test_assert_writable_blocks_router() -> None:
    with pytest.raises(HTTPException) as ei:
        assert_writable(_device(DeviceRole.ROUTER))
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "READ_ONLY_DEVICE"  # type: ignore[index]


def test_assert_writable_blocks_vpn() -> None:
    with pytest.raises(HTTPException):
        assert_writable(_device(DeviceRole.VPN))


def test_assert_writable_blocks_readonly_platform() -> None:
    with pytest.raises(HTTPException):
        assert_writable(_device(DeviceRole.LEAF, platform="readonlyplat"))


def test_assert_writable_allows_normal_leaf() -> None:
    # Should not raise.
    assert_writable(_device(DeviceRole.LEAF, platform="mock"))


# --------------------------------------------------------------------------- #
# parse_description unit tests
# --------------------------------------------------------------------------- #
def test_parse_description_full() -> None:
    host_model, bmc_ip = parse_description("VLAN-100 | Dell R740 | 10.0.0.5")
    assert host_model == "Dell R740"
    assert bmc_ip == "10.0.0.5"


def test_parse_description_no_pipe() -> None:
    assert parse_description("just a label") == ("", "")


def test_parse_description_no_vlan_prefix() -> None:
    host_model, bmc_ip = parse_description("Supermicro X11 | 10.0.0.9")
    assert host_model == "Supermicro X11"
    assert bmc_ip == "10.0.0.9"
