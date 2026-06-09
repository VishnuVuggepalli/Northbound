"""Tests for the apply flow (D3/D4 + drift guard)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northbound.drivers import registry
from northbound.drivers.base import Driver, DriverError
from northbound.models.audit_log import AuditLog
from northbound.models.change_request import ChangeRequest
from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus as S
from northbound.models.enums import DeviceRole
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
from northbound.services import audit, change_apply, requests
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
        environment="lab",
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
async def test_apply_unrelated_port_change_does_not_drift(
    db_session: AsyncSession, users2: tuple[User, User]
) -> None:
    """Drift is scoped to the request's own port: a VLAN change on a *different*
    port must NOT block applying an Eth1 request."""
    admin, alice = users2
    device = await _device(db_session, "applyconfirm")
    # Two ports at file time; the request targets Eth1 only.
    _ConfirmDriver._ports = (_port("Eth1", 1), _port("Eth2", 2))
    req = await _approved_request(db_session, device, alice, admin)

    # Mutate ONLY the unrelated port after filing.
    _ConfirmDriver._ports = (_port("Eth1", 1), _port("Eth2", 999))

    # Must not raise StateDrift; request moves forward (awaiting confirm).
    req = await change_apply.apply_request(db_session, req, device, admin)
    assert req.status != S.APPROVED
    drift = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "request.apply_blocked_drift")
    )
    assert drift is None


@pytest.mark.asyncio
async def test_apply_driver_failure_marks_failed(
    db_session: AsyncSession, users2: tuple[User, User]
) -> None:
    admin, alice = users2
    device = await _device(db_session, "applyfail")
    req = await _approved_request(db_session, device, alice, admin)

    with pytest.raises(ApplyFailed):
        await change_apply.apply_request(db_session, req, device, admin)
    # apply_request now commits the FAILED transition + failure audit before
    # raising (AUD-2). expire_on_commit=False keeps these readable on the same
    # session; the authoritative durability check is the through-get_session
    # test below, which reads from a FRESH session.
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


# --------------------------------------------------------------------------- #
# AUD-2: apply failure must survive the HTTP error path (through get_session).
# The route raises HTTPException(502) → get_session rolls back; without the
# service-owned commit the FAILED status + failure audit would be discarded and
# the request orphaned in `applying`. This drives the failure through the real
# get_session wrapper + an httpx.AsyncClient and verifies in a FRESH session.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_apply_failure_persists_through_get_session(
    db_engine: AsyncEngine,
) -> None:
    from northbound.auth.jwt import create_access_token
    from northbound.auth.password import hash_password
    from northbound.config import get_settings
    from northbound.db import get_session
    from northbound.main import app
    from northbound.models.enums import UserRole

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, autoflush=False)

    async def _real_like_get_session() -> AsyncIterator[AsyncSession]:
        """Mirror production get_session: commit on success, rollback on error."""
        session = factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    # ---- seed in its own committed session (so HTTP requests see it) --------
    async with factory() as seed:
        admin = User(username="adm-h", password_hash=hash_password("a"), role=UserRole.ADMIN)
        alice = User(username="al-h", password_hash=hash_password("b"), role=UserRole.REQUESTER)
        seed.add_all([admin, alice])
        await seed.flush()
        device = Device(
            name="dev-applyfail-http",
            environment="lab",
            platform="applyfail",
            role=DeviceRole.LEAF,
            mgmt_ip="10.0.0.77",
            prefer_native_api=True,
            encrypted_credentials=serialize_credentials(
                Credentials(username="u"), FernetCredVault.from_settings()
            ),
        )
        seed.add(device)
        await seed.flush()
        req = await requests.create_request(
            seed,
            device=device,
            port_name="Eth1",
            requested_changes=PortChange(untagged_vlan=200),
            reason="r",
            user=alice,
        )
        await requests.approve_request(seed, req, admin)
        await seed.commit()
        request_id = req.id
        admin_id = admin.id
        admin_role = admin.role

    token = create_access_token(sub=admin_id, role=admin_role, settings=get_settings())

    app.dependency_overrides[get_session] = _real_like_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/requests/{request_id}/apply",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_session, None)

    # The driver rejected → 502.
    assert resp.status_code == 502

    # ---- verify in a FRESH session: the failure record durably persisted ----
    async with factory() as check:
        reloaded = await check.scalar(select(ChangeRequest).where(ChangeRequest.id == request_id))
        assert reloaded is not None
        assert reloaded.status == S.FAILED, "FAILED status was rolled back by get_session"

        failed_event = await check.scalar(
            select(ChangeRequestEvent).where(
                ChangeRequestEvent.request_id == request_id,
                ChangeRequestEvent.to_status == S.FAILED.value,
            )
        )
        assert failed_event is not None, "failure event was rolled back"

        failed_audit = await check.scalar(
            select(AuditLog).where(AuditLog.action == "request.apply_failed")
        )
        assert failed_audit is not None, "apply_failed audit row was rolled back"
        # The persisted audit chain must still verify.
        ok, index = await audit.verify_chain(check)
        assert ok is True, f"audit chain broke at index {index}"


# ── R3 concurrency: double-apply guard (CON-1) ──────────────────────────────


class _CountingConfirmDriver(_BaseTestDriver):
    """Commit-confirm driver that counts apply_change calls."""

    platform_id = "applycount"
    display_name = "Counting (test)"
    capabilities = _BASE_CAPS
    apply_calls = 0

    async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
        type(self).apply_calls += 1
        return ApplyResult(success=True, confirm_token="tok-r3", confirm_deadline_at=9999.0)


@pytest.mark.asyncio
async def test_second_apply_attempt_pushes_config_exactly_once(
    db_session: AsyncSession, users2: tuple[User, User]
) -> None:
    """Two apply_request attempts on the same request → the driver is invoked
    EXACTLY once; the second attempt (on the now-claimed row) raises
    AlreadyClaimed and never touches the device. Headline CON-1 proof against
    double-apply. Attempts run sequentially because a single AsyncSession is not
    concurrency-safe; in production each request has its own session and the
    atomic UPDATE...WHERE on the shared DB row is the serialization point, which
    is exactly what claim_transition implements."""
    registry.register(_CountingConfirmDriver)
    _CountingConfirmDriver.apply_calls = 0
    try:
        admin, alice = users2
        device = await _device(db_session, "applycount")
        request = await _approved_request(db_session, device, alice, admin)

        # First attempt wins the claim, pushes config, ends awaiting_confirm.
        first = await change_apply.apply_request(db_session, request, device, admin)
        assert first.status == S.AWAITING_CONFIRM

        # Second attempt on the now-claimed request is rejected BEFORE any
        # device I/O — the early status guard (no longer approved/pending) or,
        # in a true race where both observers see APPROVED, the atomic
        # approved/pending→applying claim matching 0 rows.
        with pytest.raises((change_apply.ApplyError, requests.AlreadyClaimed)):
            await change_apply.apply_request(db_session, request, device, admin)

        # Device was pushed exactly once across both attempts.
        assert _CountingConfirmDriver.apply_calls == 1, (
            f"double-apply: driver called {_CountingConfirmDriver.apply_calls}x"
        )
    finally:
        registry._REGISTRY.pop(_CountingConfirmDriver.platform_id, None)
        _CountingConfirmDriver.apply_calls = 0


@pytest.mark.asyncio
async def test_claim_transition_second_caller_rejected(
    db_session: AsyncSession, users2: tuple[User, User]
) -> None:
    """claim_transition is the authoritative guard: the first claim flips
    approved→applying; a second claim on the now-applying row matches 0 rows
    and raises AlreadyClaimed (no device I/O happens on that path)."""
    admin, alice = users2
    device = await _device(db_session, "applyconfirm")
    request = await _approved_request(db_session, device, alice, admin)

    await requests.claim_transition(
        db_session, request, expected=[S.APPROVED, S.PENDING], to_status=S.APPLYING, actor=admin.id
    )
    assert request.status == S.APPLYING

    with pytest.raises(requests.AlreadyClaimed):
        await requests.claim_transition(
            db_session,
            request,
            expected=[S.APPROVED, S.PENDING],
            to_status=S.APPLYING,
            actor=admin.id,
        )


def test_apply_stale_seconds_clamped_to_invariant() -> None:
    """CON-3: reconciler_apply_stale_seconds is clamped up so it comfortably
    exceeds the commit-confirm window (can't kill a slow-but-live apply)."""
    from northbound.config import Settings

    s = Settings(commit_confirm_seconds=60, reconciler_apply_stale_seconds=10)
    assert s.reconciler_apply_stale_seconds >= s.commit_confirm_seconds
    # A generous value is left untouched.
    s2 = Settings(commit_confirm_seconds=60, reconciler_apply_stale_seconds=600)
    assert s2.reconciler_apply_stale_seconds == 600
