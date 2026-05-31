"""Reconciler tests (D3/D4) — driven with an injected ``now`` (no real timers).

Covers the decision table and idempotency:
  * awaiting_confirm past deadline      → failed + audit + event
  * awaiting_confirm before deadline    → untouched
  * applying with a stale latest event  → failed "interrupted"
  * applying with a fresh latest event  → untouched
  * terminal states                     → untouched
  * idempotent: reconcile_once twice → exactly one failure, not two
"""

from __future__ import annotations

import datetime as dt

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.audit_log import AuditLog
from northbound.models.change_request import ChangeRequest
from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus as S
from northbound.services import reconciler

_NOW = dt.datetime(2026, 5, 30, 12, 0, 0, tzinfo=dt.UTC)


async def _make_request(
    session: AsyncSession,
    device: Device,
    *,
    status: S,
    confirm_deadline_at: float | None = None,
    confirm_token: str | None = None,
    updated_at: dt.datetime | None = None,
) -> ChangeRequest:
    """Insert a request directly in the target status (bypassing the flow).

    ``updated_at`` is the CON-3 liveness heartbeat the reconciler folds into
    its staleness decision for APPLYING rows; pass it explicitly so tests don't
    depend on the real wall clock (which the server_default would otherwise
    stamp, and which is unrelated to the injected ``now``).
    """
    request = ChangeRequest(
        device_id=device.id,
        port_name="Eth1",
        requested_by="alice",
        requested_changes={"untagged_vlan": 20},
        reason="test",
        status=status,
        confirm_token=confirm_token,
        confirm_deadline_at=confirm_deadline_at,
    )
    session.add(request)
    await session.flush()
    if updated_at is not None:
        request.updated_at = updated_at
        session.add(request)
        await session.flush()
    return request


async def _add_event(
    session: AsyncSession,
    request: ChangeRequest,
    *,
    to_status: S,
    created_at: dt.datetime,
) -> None:
    """Append a transition event with an explicit created_at (for staleness)."""
    event = ChangeRequestEvent(
        request_id=request.id,
        from_status="",
        to_status=to_status.value,
        actor="system:test",
        created_at=created_at,
    )
    session.add(event)
    await session.flush()


async def _failed_count(session: AsyncSession) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(ChangeRequest).where(ChangeRequest.status == S.FAILED)
        )
    ) or 0


@pytest_asyncio.fixture
async def device(db_session: AsyncSession, mock_device: Device) -> Device:
    return mock_device


# --------------------------------------------------------------------------- #
# awaiting_confirm
# --------------------------------------------------------------------------- #
async def test_awaiting_confirm_past_deadline_fails(
    db_session: AsyncSession,
    device: Device,
) -> None:
    """Past deadline → failed, with a transition event and an audit row."""
    past = (_NOW - dt.timedelta(seconds=5)).timestamp()
    request = await _make_request(
        db_session,
        device,
        status=S.AWAITING_CONFIRM,
        confirm_deadline_at=past,
        confirm_token="mock-token",
    )

    count = await reconciler.reconcile_once(db_session, now=_NOW)
    await db_session.refresh(request)

    assert count == 1
    assert request.status == S.FAILED
    assert request.confirm_token is None
    assert request.confirm_deadline_at is None

    # A FAILED transition event was logged.
    events = (
        await db_session.scalars(
            select(ChangeRequestEvent).where(ChangeRequestEvent.request_id == request.id)
        )
    ).all()
    assert any(e.to_status == S.FAILED.value for e in events)

    # An audit row records the auto-revert.
    audits = (
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "request.auto_reverted"))
    ).all()
    assert len(audits) == 1
    assert audits[0].result == "reverted"


async def test_awaiting_confirm_before_deadline_untouched(
    db_session: AsyncSession,
    device: Device,
) -> None:
    """Still inside the confirm window → left untouched."""
    future = (_NOW + dt.timedelta(seconds=30)).timestamp()
    request = await _make_request(
        db_session,
        device,
        status=S.AWAITING_CONFIRM,
        confirm_deadline_at=future,
        confirm_token="mock-token",
    )

    count = await reconciler.reconcile_once(db_session, now=_NOW)
    await db_session.refresh(request)

    assert count == 0
    assert request.status == S.AWAITING_CONFIRM
    assert request.confirm_token == "mock-token"


# --------------------------------------------------------------------------- #
# applying
# --------------------------------------------------------------------------- #
async def test_applying_stale_fails_interrupted(
    db_session: AsyncSession,
    device: Device,
) -> None:
    """An applying request whose latest event AND heartbeat are old → failed
    'interrupted'."""
    stale = _NOW - dt.timedelta(seconds=600)
    request = await _make_request(db_session, device, status=S.APPLYING, updated_at=stale)
    await _add_event(db_session, request, to_status=S.APPLYING, created_at=stale)

    count = await reconciler.reconcile_once(db_session, now=_NOW, apply_stale_seconds=300)
    await db_session.refresh(request)

    assert count == 1
    assert request.status == S.FAILED

    audits = (
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "request.interrupted"))
    ).all()
    assert len(audits) == 1
    assert audits[0].result == "error"


async def test_applying_fresh_event_untouched(
    db_session: AsyncSession,
    device: Device,
) -> None:
    """An applying request with a recent event → genuinely in progress, left be."""
    fresh = _NOW - dt.timedelta(seconds=2)
    request = await _make_request(db_session, device, status=S.APPLYING, updated_at=fresh)
    await _add_event(db_session, request, to_status=S.APPLYING, created_at=fresh)

    count = await reconciler.reconcile_once(db_session, now=_NOW, apply_stale_seconds=300)
    await db_session.refresh(request)

    assert count == 0
    assert request.status == S.APPLYING


async def test_applying_fresh_heartbeat_old_event_untouched(
    db_session: AsyncSession,
    device: Device,
) -> None:
    """CON-3 regression: the only transition event is the OLD claim event, but
    the mid-apply heartbeat (updated_at) is fresh → a slow-but-live apply must
    NOT be reaped. Guards against the heartbeat being written to a column the
    reconciler never reads."""
    old_event = _NOW - dt.timedelta(seconds=600)
    fresh_heartbeat = _NOW - dt.timedelta(seconds=2)
    request = await _make_request(db_session, device, status=S.APPLYING, updated_at=fresh_heartbeat)
    await _add_event(db_session, request, to_status=S.APPLYING, created_at=old_event)

    count = await reconciler.reconcile_once(db_session, now=_NOW, apply_stale_seconds=300)
    await db_session.refresh(request)

    assert count == 0
    assert request.status == S.APPLYING


# --------------------------------------------------------------------------- #
# terminal states
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", [S.APPLIED, S.FAILED, S.REJECTED, S.REVERTED, S.PENDING])
async def test_terminal_and_non_inflight_untouched(
    db_session: AsyncSession,
    device: Device,
    status: S,
) -> None:
    """Terminal / non-in-flight requests are never selected by the reconciler."""
    request = await _make_request(db_session, device, status=status)

    count = await reconciler.reconcile_once(db_session, now=_NOW)
    await db_session.refresh(request)

    assert count == 0
    assert request.status == status


# --------------------------------------------------------------------------- #
# idempotency
# --------------------------------------------------------------------------- #
async def test_reconcile_once_is_idempotent(
    db_session: AsyncSession,
    device: Device,
) -> None:
    """Running twice over the same data → exactly one failure, not two."""
    past = (_NOW - dt.timedelta(seconds=5)).timestamp()
    await _make_request(
        db_session,
        device,
        status=S.AWAITING_CONFIRM,
        confirm_deadline_at=past,
        confirm_token="mock-token",
    )

    first = await reconciler.reconcile_once(db_session, now=_NOW)
    second = await reconciler.reconcile_once(db_session, now=_NOW)

    assert first == 1
    assert second == 0  # already terminal on the second pass — nothing to do
    assert await _failed_count(db_session) == 1

    # Exactly one auto-revert audit row, not two.
    audits = (
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "request.auto_reverted"))
    ).all()
    assert len(audits) == 1
