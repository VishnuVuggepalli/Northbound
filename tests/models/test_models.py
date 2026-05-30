"""ORM model tests: creation, UNIQUE constraints, FKs, enum round-trips."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models import (
    AuditLog,
    ChangeRequest,
    ChangeRequestEvent,
    ChangeRequestStatus,
    ConfigBackup,
    Device,
    DeviceRole,
    Environment,
    PortMetadata,
    User,
    UserRole,
)


async def _make_device(session: AsyncSession, name: str = "lab-leaf-1") -> Device:
    device = Device(
        name=name,
        environment=Environment.LAB,
        platform="mock",
        role=DeviceRole.LEAF,
        mgmt_ip="10.0.0.1",
    )
    session.add(device)
    await session.flush()
    return device


async def test_create_user_and_enum_round_trip(db_session: AsyncSession) -> None:
    user = User(username="admin", password_hash="x", role=UserRole.ADMIN)
    db_session.add(user)
    await db_session.commit()

    fetched = (await db_session.execute(select(User).where(User.username == "admin"))).scalar_one()
    assert fetched.role is UserRole.ADMIN
    assert fetched.id and len(fetched.id) == 36
    assert isinstance(fetched.created_at, dt.datetime)


async def test_user_username_unique(db_session: AsyncSession) -> None:
    db_session.add(User(username="dup", password_hash="a", role=UserRole.REQUESTER))
    await db_session.commit()
    db_session.add(User(username="dup", password_hash="b", role=UserRole.ADMIN))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_device_name_unique(db_session: AsyncSession) -> None:
    await _make_device(db_session, "sw1")
    await db_session.commit()
    db_session.add(
        Device(
            name="sw1",
            environment=Environment.LAB,
            platform="mock",
            role=DeviceRole.LEAF,
            mgmt_ip="10.0.0.2",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_device_enum_round_trip(db_session: AsyncSession) -> None:
    await _make_device(db_session)
    await db_session.commit()
    fetched = (await db_session.execute(select(Device))).scalar_one()
    assert fetched.environment is Environment.LAB
    assert fetched.role is DeviceRole.LEAF
    assert fetched.prefer_native_api is True
    assert fetched.encrypted_credentials is None


async def test_port_metadata_unique_device_port(db_session: AsyncSession) -> None:
    device = await _make_device(db_session)
    db_session.add(PortMetadata(device_id=device.id, port_name="eth1"))
    await db_session.commit()
    db_session.add(PortMetadata(device_id=device.id, port_name="eth1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_port_metadata_same_port_different_device(
    db_session: AsyncSession,
) -> None:
    d1 = await _make_device(db_session, "d1")
    d2 = await _make_device(db_session, "d2")
    db_session.add(PortMetadata(device_id=d1.id, port_name="eth1"))
    db_session.add(PortMetadata(device_id=d2.id, port_name="eth1"))
    await db_session.commit()  # no conflict across devices


async def test_port_metadata_fk_enforced(db_session: AsyncSession) -> None:
    db_session.add(PortMetadata(device_id="does-not-exist", port_name="eth1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_change_request_json_and_status_round_trip(
    db_session: AsyncSession,
) -> None:
    device = await _make_device(db_session)
    cr = ChangeRequest(
        device_id=device.id,
        port_name="eth1",
        requested_by="alice",
        requested_changes={"untagged_vlan": 10, "tagged_vlans": [20, 30]},
        reason="move host",
    )
    db_session.add(cr)
    await db_session.commit()

    fetched = (await db_session.execute(select(ChangeRequest))).scalar_one()
    assert fetched.status is ChangeRequestStatus.PENDING
    assert fetched.requested_changes == {
        "untagged_vlan": 10,
        "tagged_vlans": [20, 30],
    }
    assert fetched.confirm_deadline_at is None


async def test_change_request_event_fk(db_session: AsyncSession) -> None:
    device = await _make_device(db_session)
    cr = ChangeRequest(
        device_id=device.id,
        port_name="eth1",
        requested_by="alice",
        requested_changes={},
    )
    db_session.add(cr)
    await db_session.flush()
    db_session.add(
        ChangeRequestEvent(
            request_id=cr.id,
            from_status="pending",
            to_status="approved",
            actor="admin",
            payload={"comment": "ok"},
        )
    )
    await db_session.commit()
    evt = (await db_session.execute(select(ChangeRequestEvent))).scalar_one()
    assert evt.to_status == "approved"
    assert evt.payload == {"comment": "ok"}


async def test_audit_log_hash_chain_columns(db_session: AsyncSession) -> None:
    entry = AuditLog(
        action="device.onboarded",
        result="ok",
        row_hash="abc123",
        prev_hash=None,
        before=None,
        after={"name": "sw1"},
    )
    db_session.add(entry)
    await db_session.commit()
    fetched = (await db_session.execute(select(AuditLog))).scalar_one()
    assert fetched.row_hash == "abc123"
    assert fetched.prev_hash is None
    assert fetched.after == {"name": "sw1"}


async def test_config_backup_create(db_session: AsyncSession) -> None:
    device = await _make_device(db_session)
    db_session.add(
        ConfigBackup(
            device_id=device.id,
            config_text="hostname sw1\n",
            fetched_at=dt.datetime.now(dt.UTC),
            fetched_by="admin",
        )
    )
    await db_session.commit()
    backup = (await db_session.execute(select(ConfigBackup))).scalar_one()
    assert backup.config_text == "hostname sw1\n"
