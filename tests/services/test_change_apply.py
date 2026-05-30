"""Tests for the apply flow (D3/D4 + drift guard)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.drivers import registry
from northbound.drivers.base import Driver, DriverError
from northbound.models.audit_log import AuditLog
from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus as S
from northbound.models.enums import DeviceRole, Environment
from northbound.models.user import User
from northbound.schemas.driver import (
    ApplyResult,
    AuthMethod,
    ConfigDiff,
    Credentials,
    DiscoveryResult,
    DriverCapabilities,
    PortChange,
    PortState,
    TestResult,
)
from northbound.services import change_apply, requests
from northbound.services.change_apply import ApplyFailed, StateDrift
from northbound.services.credvault import FernetCredVault, serialize_credentials

_BASE_CAPS = DriverCapabilities(
    writable=True,
    supports_commit_confirm=True,
    native_api_available=True,
    supports_snmp_read=False,
    supports_lldp=False,
    max_concurrency=5,
    auth_methods=[AuthMethod.PASSWORD],
)


def _port(name: str, vlan: int | None) -> PortState:
    return PortState(
        name=name,
        admin_up=True,
        link_up=True,
        speed_mbps=1000,
        duplex="full",
        mac=None,
        mtu=1500,
        untagged_vlan=vlan,
        tagged_vlans=(),
        description="",
        host_model="",
        bmc_ip="",
        notes="",
    )


class _BaseTestDriver(Driver):
    _ports: tuple[PortState, ...] = (_port("Eth1", 1),)

    async def test_credentials(self) -> TestResult:
        return TestResult(ok=True, latency_ms=1.0, platform_version="x")

    async def discover(self) -> DiscoveryResult:
        return DiscoveryResult(hostname="h", ports=self._ports, running_config="cfg")

    async def reachable(self) -> bool:
        return True

    async def get_ports(self) -> list[PortState]:
        return list(type(self)._ports)

    async def get_running_config(self) -> str:
        return "running-cfg"

    async def backup_config(self) -> str:
        return "backup-cfg"

    async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
        return ConfigDiff(
            summary=f"update {port}",
            raw_before="before",
            raw_after="after",
            commands=(f"interface {port}", "switchport access vlan X"),
        )


class _ConfirmDriver(_BaseTestDriver):
    """Commit-confirm platform — apply returns a token."""

    platform_id = "applyconfirm"
    display_name = "Confirm (test)"
    capabilities = _BASE_CAPS

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        return ApplyResult(success=True, confirm_token="tok-123", confirm_deadline_at=9999.0)

    async def confirm(self, apply_token: str) -> None:
        return None


class _NoConfirmDriver(_BaseTestDriver):
    """Platform with no native confirm — apply returns no token."""

    platform_id = "applynoconfirm"
    display_name = "No-confirm (test)"
    capabilities = _BASE_CAPS

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        return ApplyResult(success=True, confirm_token=None, confirm_deadline_at=None)


class _FailDriver(_BaseTestDriver):
    """apply_change raises a DriverError."""

    platform_id = "applyfail"
    display_name = "Fail (test)"
    capabilities = _BASE_CAPS

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        raise DriverError("device rejected the config")


_DRIVERS: tuple[type[Driver], ...] = (_ConfirmDriver, _NoConfirmDriver, _FailDriver)


@pytest.fixture(autouse=True)
def _register() -> Iterator[None]:
    for cls in _DRIVERS:
        registry.register(cls)
    try:
        yield
    finally:
        for cls in _DRIVERS:
            registry._REGISTRY.pop(cls.platform_id, None)
        _ConfirmDriver._ports = (_port("Eth1", 1),)


async def _device(db_session: AsyncSession, platform: str) -> Device:
    vault = FernetCredVault.from_settings()
    device = Device(
        name=f"dev-{platform}",
        environment=Environment.LAB,
        platform=platform,
        role=DeviceRole.LEAF,
        mgmt_ip="10.0.0.7",
        prefer_native_api=True,
        encrypted_credentials=serialize_credentials(Credentials(username="u"), vault),
    )
    db_session.add(device)
    await db_session.flush()
    return device


async def _approved_request(db_session: AsyncSession, device: Device, alice: User, admin: User):
    req = await requests.create_request(
        db_session,
        device=device,
        port_name="Eth1",
        requested_changes=PortChange(untagged_vlan=200),
        reason="r",
        user=alice,
    )
    await requests.approve_request(db_session, req, admin)
    return req


@pytest_asyncio.fixture
async def users2(db_session: AsyncSession):
    from northbound.auth.password import hash_password
    from northbound.models.enums import UserRole

    admin = User(username="adm", password_hash=hash_password("a"), role=UserRole.ADMIN)
    alice = User(username="al", password_hash=hash_password("b"), role=UserRole.REQUESTER)
    db_session.add_all([admin, alice])
    await db_session.flush()
    return admin, alice


@pytest.mark.asyncio
async def test_apply_happy_path_commit_confirm(
    db_session: AsyncSession, users2: tuple[User, User]
) -> None:
    admin, alice = users2
    device = await _device(db_session, "applyconfirm")
    req = await _approved_request(db_session, device, alice, admin)

    req = await change_apply.apply_request(db_session, req, device, admin)
    assert req.status == S.AWAITING_CONFIRM
    assert req.confirm_token == "tok-123"
    assert req.confirm_deadline_at == 9999.0
    assert req.diff_text == "after"

    # Backup created.
    backups = await db_session.scalar(
        select(func.count()).select_from(ConfigBackup).where(ConfigBackup.device_id == device.id)
    )
    assert backups == 1

    # applied audit written, no creds.
    applied = await db_session.scalar(select(AuditLog).where(AuditLog.action == "request.applied"))
    assert applied is not None
    assert "switch-pw" not in str(applied.after)

    # events: pending, approved, applying, awaiting_confirm
    events = (
        await db_session.scalars(
            select(ChangeRequestEvent).where(ChangeRequestEvent.request_id == req.id)
        )
    ).all()
    statuses = {e.to_status for e in events}
    assert S.APPLYING.value in statuses
    assert S.AWAITING_CONFIRM.value in statuses

    # Then confirm → applied.
    req = await change_apply.confirm_request(db_session, req, device, admin)
    assert req.status == S.APPLIED
    assert req.confirm_token is None
    assert req.applied_at is not None


@pytest.mark.asyncio
async def test_apply_no_confirm_platform_applies_directly(
    db_session: AsyncSession, users2: tuple[User, User]
) -> None:
    admin, alice = users2
    device = await _device(db_session, "applynoconfirm")
    req = await _approved_request(db_session, device, alice, admin)
    req = await change_apply.apply_request(db_session, req, device, admin)
    assert req.status == S.APPLIED
    assert req.confirm_token is None
    assert req.applied_at is not None


@pytest.mark.asyncio
async def test_apply_stale_state_blocks(
    db_session: AsyncSession, users2: tuple[User, User]
) -> None:
    admin, alice = users2
    device = await _device(db_session, "applyconfirm")
    req = await _approved_request(db_session, device, alice, admin)

    # Mutate live ports after the request was filed → fingerprint mismatch.
    _ConfirmDriver._ports = (_port("Eth1", 777),)

    with pytest.raises(StateDrift):
        await change_apply.apply_request(db_session, req, device, admin)
    # Status unchanged (still approved).
    assert req.status == S.APPROVED
    # A drift audit row was recorded.
    drift = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "request.apply_blocked_drift")
    )
    assert drift is not None


@pytest.mark.asyncio
async def test_apply_driver_failure_marks_failed(
    db_session: AsyncSession, users2: tuple[User, User]
) -> None:
    admin, alice = users2
    device = await _device(db_session, "applyfail")
    req = await _approved_request(db_session, device, alice, admin)

    with pytest.raises(ApplyFailed):
        await change_apply.apply_request(db_session, req, device, admin)
    assert req.status == S.FAILED
    failed_audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "request.apply_failed")
    )
    assert failed_audit is not None
    # failed event present
    events = (
        await db_session.scalars(
            select(ChangeRequestEvent).where(ChangeRequestEvent.request_id == req.id)
        )
    ).all()
    assert S.FAILED.value in {e.to_status for e in events}
