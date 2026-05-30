"""Tests for the change-request workflow + state machine."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus as S
from northbound.models.enums import DeviceRole, Environment
from northbound.models.user import User
from northbound.schemas.driver import PortChange
from northbound.services import requests
from northbound.services.requests import IllegalTransition, RequestError, can_transition


@pytest.mark.asyncio
async def test_create_captures_fingerprint_and_events(
    db_session: AsyncSession, mock_device: Device, users: tuple[User, User]
) -> None:
    _, alice = users
    req = await requests.create_request(
        db_session,
        device=mock_device,
        port_name="Ethernet1",
        requested_changes=PortChange(untagged_vlan=200),
        reason="put on vlan 200",
        user=alice,
    )
    assert req.status == S.PENDING
    assert req.device_state_fingerprint  # captured at file time
    # An initial event row was written.
    count = await db_session.scalar(
        select(func.count())
        .select_from(ChangeRequestEvent)
        .where(ChangeRequestEvent.request_id == req.id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_create_against_router_is_403(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    _, alice = users
    router = Device(
        name="core-router",
        environment=Environment.DC,
        platform="mock",
        role=DeviceRole.ROUTER,
        mgmt_ip="10.0.0.1",
        prefer_native_api=True,
    )
    db_session.add(router)
    await db_session.flush()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        await requests.create_request(
            db_session,
            device=router,
            port_name="Eth1",
            requested_changes=PortChange(untagged_vlan=10),
            reason="x",
            user=alice,
        )
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_approve_transition_and_event(
    db_session: AsyncSession, mock_device: Device, users: tuple[User, User]
) -> None:
    admin, alice = users
    req = await requests.create_request(
        db_session,
        device=mock_device,
        port_name="Ethernet1",
        requested_changes=PortChange(untagged_vlan=200),
        reason="r",
        user=alice,
    )
    await requests.approve_request(db_session, req, admin)
    assert req.status == S.APPROVED
    assert req.reviewer_id == admin.id
    events = (
        await db_session.scalars(
            select(ChangeRequestEvent).where(ChangeRequestEvent.request_id == req.id)
        )
    ).all()
    # create + approve
    assert {e.to_status for e in events} == {S.PENDING.value, S.APPROVED.value}


@pytest.mark.asyncio
async def test_reject_requires_comment(
    db_session: AsyncSession, mock_device: Device, users: tuple[User, User]
) -> None:
    admin, alice = users
    req = await requests.create_request(
        db_session,
        device=mock_device,
        port_name="Ethernet1",
        requested_changes=PortChange(untagged_vlan=200),
        reason="r",
        user=alice,
    )
    with pytest.raises(RequestError):
        await requests.reject_request(db_session, req, admin, comment="  ")
    # status unchanged
    assert req.status == S.PENDING

    await requests.reject_request(db_session, req, admin, comment="not now")
    assert req.status == S.REJECTED
    assert req.reviewer_comment == "not now"


@pytest.mark.asyncio
async def test_illegal_transition_raises(
    db_session: AsyncSession, mock_device: Device, users: tuple[User, User]
) -> None:
    admin, alice = users
    req = await requests.create_request(
        db_session,
        device=mock_device,
        port_name="Ethernet1",
        requested_changes=PortChange(untagged_vlan=200),
        reason="r",
        user=alice,
    )
    await requests.approve_request(db_session, req, admin)
    # Cannot reject an already-approved request via the pending->rejected guard?
    # approved->rejected IS legal; approved->approved is not.
    with pytest.raises(IllegalTransition):
        await requests.record_transition(db_session, req, to_status=S.APPROVED, actor=admin.id)


def test_transition_table_terminal_states() -> None:
    assert can_transition(S.PENDING, S.APPROVED)
    assert can_transition(S.APPROVED, S.APPLYING)
    assert can_transition(S.APPLYING, S.AWAITING_CONFIRM)
    assert can_transition(S.AWAITING_CONFIRM, S.APPLIED)
    assert not can_transition(S.APPLIED, S.APPLYING)
    assert not can_transition(S.REJECTED, S.APPROVED)


@pytest.mark.asyncio
async def test_list_filters(
    db_session: AsyncSession, mock_device: Device, users: tuple[User, User]
) -> None:
    admin, alice = users
    r1 = await requests.create_request(
        db_session,
        device=mock_device,
        port_name="Ethernet1",
        requested_changes=PortChange(untagged_vlan=10),
        reason="r1",
        user=alice,
    )
    await requests.create_request(
        db_session,
        device=mock_device,
        port_name="Ethernet2",
        requested_changes=PortChange(untagged_vlan=20),
        reason="r2",
        user=admin,
    )
    mine = await requests.list_requests(db_session, mine_user_id=alice.id)
    assert [r.id for r in mine] == [r1.id]

    pending = await requests.list_requests(db_session, status=S.PENDING)
    assert len(pending) == 2
