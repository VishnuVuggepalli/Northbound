"""HTTP tests for the ports + config API surface."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("NB_SECRET_KEY", "unit-test-secret-key")
os.environ.setdefault("NB_MASTER_KEY", "wDPYj3kZ3qbY8m0v6m2nQ1rJf7xq9o5xS3uVc8nH0cE=")

from northbound.api import ports as ports_api
from northbound.auth.jwt import create_access_token
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.main import app
from northbound.models.audit_log import AuditLog
from northbound.models.device import Device
from northbound.models.enums import DeviceRole, UserRole
from northbound.models.port_metadata import PortMetadata
from northbound.models.user import User
from northbound.schemas.driver import Credentials
from northbound.services import port_state
from northbound.services.credvault import FernetCredVault, serialize_credentials

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    port_state._cache.clear()
    ports_api._config_cache.clear()
    yield
    port_state._cache.clear()
    ports_api._config_cache.clear()


@pytest_asyncio.fixture
async def seeded(
    db_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, User, User, Device]]:
    vault = FernetCredVault.from_settings()
    admin = User(username="admin", password_hash=hash_password("a"), role=UserRole.ADMIN)
    alice = User(username="alice", password_hash=hash_password("b"), role=UserRole.REQUESTER)
    leaf = Device(
        name="lab-leaf",
        environment="lab",
        platform="mock",
        role=DeviceRole.LEAF,
        mgmt_ip="10.0.0.5",
        prefer_native_api=True,
        encrypted_credentials=serialize_credentials(Credentials(username="u"), vault),
    )
    db_session.add_all([admin, alice, leaf])
    await db_session.flush()
    # Seed metadata for one port.
    db_session.add(
        PortMetadata(device_id=leaf.id, port_name="Ethernet3", host_model="HPE", bmc_ip="10.0.0.99")
    )
    await db_session.flush()
    yield db_session, admin, alice, leaf


@pytest_asyncio.fixture
async def client(
    seeded: tuple[AsyncSession, User, User, Device],
) -> AsyncIterator[AsyncClient]:
    session = seeded[0]

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(sub=user.id, role=user.role, settings=get_settings())
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_ports_lists_and_merges_metadata(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device]
) -> None:
    _, _, alice, leaf = seeded
    resp = await client.get(f"/api/devices/{leaf.id}/ports", headers=_bearer(alice))
    assert resp.status_code == 200
    ports = resp.json()
    assert len(ports) == 8
    eth3 = next(p for p in ports if p["name"] == "Ethernet3")
    assert eth3["host_model"] == "HPE"
    assert eth3["bmc_ip"] == "10.0.0.99"


@pytest.mark.asyncio
async def test_get_ports_refresh_param(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device]
) -> None:
    _, _, alice, leaf = seeded
    resp = await client.get(f"/api/devices/{leaf.id}/ports?refresh=true", headers=_bearer(alice))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_patch_metadata_edit_audit_and_last_human_edit(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device]
) -> None:
    session, admin, _, leaf = seeded
    resp = await client.patch(
        f"/api/devices/{leaf.id}/ports/Ethernet1",
        headers=_bearer(admin),
        json={"host_model": "Dell R740", "notes": "rack 7"},
    )
    assert resp.status_code == 200
    assert resp.json()["host_model"] == "Dell R740"
    assert resp.json()["last_human_edit_by"] == admin.id

    pm = await session.scalar(
        select(PortMetadata).where(
            PortMetadata.device_id == leaf.id, PortMetadata.port_name == "Ethernet1"
        )
    )
    assert pm is not None
    assert pm.last_human_edit_at is not None
    assert pm.last_human_edit_by == admin.id

    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "port.metadata_edited"))
    assert audit is not None


@pytest.mark.asyncio
async def test_patch_metadata_requires_admin(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device]
) -> None:
    _, _, alice, leaf = seeded
    resp = await client.patch(
        f"/api/devices/{leaf.id}/ports/Ethernet1",
        headers=_bearer(alice),
        json={"notes": "x"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_port_detail_includes_history(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device]
) -> None:
    _, admin, _, leaf = seeded
    await client.patch(
        f"/api/devices/{leaf.id}/ports/Ethernet1",
        headers=_bearer(admin),
        json={"notes": "edited"},
    )
    detail = await client.get(f"/api/devices/{leaf.id}/ports/Ethernet1", headers=_bearer(admin))
    assert detail.status_code == 200
    body = detail.json()
    assert body["port"]["name"] == "Ethernet1"
    assert any(h["action"] == "port.metadata_edited" for h in body["history"])


@pytest.mark.asyncio
async def test_config_backup_and_diff(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device]
) -> None:
    _, admin, _, leaf = seeded
    # Read config (cached path).
    cfg = await client.get(f"/api/devices/{leaf.id}/config", headers=_bearer(admin))
    assert cfg.status_code == 200
    assert cfg.json()["config_text"]

    # Backup now.
    backup = await client.post(f"/api/devices/{leaf.id}/config/backup", headers=_bearer(admin))
    assert backup.status_code == 201
    bid = backup.json()["id"]

    # List backups.
    lst = await client.get(f"/api/devices/{leaf.id}/config/backups", headers=_bearer(admin))
    assert lst.status_code == 200
    assert any(b["id"] == bid for b in lst.json())

    # Diff (same config → empty/near-empty diff, but endpoint works).
    diff = await client.get(
        f"/api/devices/{leaf.id}/config/backups/{bid}/diff", headers=_bearer(admin)
    )
    assert diff.status_code == 200
    assert diff.json()["backup_id"] == bid


@pytest.mark.asyncio
async def test_config_backup_requires_admin(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device]
) -> None:
    _, _, alice, leaf = seeded
    resp = await client.post(f"/api/devices/{leaf.id}/config/backup", headers=_bearer(alice))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ports_device_not_found(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device]
) -> None:
    _, _, alice, _ = seeded
    resp = await client.get("/api/devices/nope/ports", headers=_bearer(alice))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Direct-write confirm failure must leave a trace (backup + failure audit),
# not vanish in the route's 502 rollback.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_direct_write_confirm_failure_persists_audit_and_backup(
    db_session: AsyncSession,
) -> None:
    from fastapi import HTTPException

    from northbound.drivers import registry
    from northbound.drivers.base import Driver, DriverError
    from northbound.models.config_backup import ConfigBackup
    from northbound.schemas.driver import (
        ApplyResult,
        AuthMethod,
        ConfigDiff,
        DiscoveryResult,
        DriverCapabilities,
        PortChange,
        PortState,
        TestResult,
    )

    class _ConfirmFailDriver(Driver):
        platform_id = "directconfirmfail"
        display_name = "ConfirmFail (test)"
        capabilities = DriverCapabilities(
            writable=True,
            supports_commit_confirm=True,
            native_api_available=True,
            supports_snmp_read=False,
            supports_lldp=False,
            max_concurrency=5,
            auth_methods=[AuthMethod.PASSWORD],
        )

        async def test_credentials(self) -> TestResult:
            return TestResult(ok=True, latency_ms=1.0, platform_version="x")

        async def discover(self) -> DiscoveryResult:
            return DiscoveryResult(hostname="h", ports=(), running_config="cfg")

        async def reachable(self) -> bool:
            return True

        async def get_ports(self) -> list[PortState]:
            return []

        async def get_running_config(self) -> str:
            return "running-cfg"

        async def backup_config(self) -> str:
            return "backup-cfg"

        async def render_change(self, port: str, change: PortChange) -> ConfigDiff:
            return ConfigDiff(summary="s", raw_before="b", raw_after="a", commands=("c",))

        async def apply_change(self, diff: ConfigDiff, *, confirm_seconds: int = 60) -> ApplyResult:
            return ApplyResult(success=True, confirm_token="tok", confirm_deadline_at=9999.0)

        async def confirm(self, apply_token: str) -> None:
            raise DriverError("confirm rejected by device")

    registry.register(_ConfirmFailDriver)
    try:
        vault = FernetCredVault.from_settings()
        admin = User(username="dwadmin", password_hash=hash_password("a"), role=UserRole.ADMIN)
        device = Device(
            name="dw-leaf",
            environment="lab",
            platform="directconfirmfail",
            role=DeviceRole.LEAF,
            mgmt_ip="10.0.0.9",
            prefer_native_api=True,
            encrypted_credentials=serialize_credentials(Credentials(username="u"), vault),
        )
        db_session.add_all([admin, device])
        await db_session.flush()

        with pytest.raises(HTTPException) as exc_info:
            await ports_api._apply_direct_port_change(
                db_session,
                device,
                "Eth1",
                PortChange(description="x"),
                admin=admin,
                action="port.description_set",
                after={"description": "x"},
            )
        assert exc_info.value.status_code == 502

        # The failure audit + the pre-write backup were committed despite the 502.
        audit_row = await db_session.scalar(
            select(AuditLog).where(
                AuditLog.action == "port.description_set", AuditLog.result == "error"
            )
        )
        assert audit_row is not None
        backup = await db_session.scalar(
            select(ConfigBackup).where(ConfigBackup.device_id == device.id)
        )
        assert backup is not None
    finally:
        registry._REGISTRY.pop("directconfirmfail", None)
