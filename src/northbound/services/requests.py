"""Change-request workflow — a persisted state machine (principal-engineering D3).

States (``ChangeRequestStatus``):

    pending → approved → applying → awaiting_confirm → applied
       │  └──────────────────────────────────────────→ failed
       └──→ rejected
    awaiting_confirm → reverted   (reconciler / manual revert path)

Every transition writes a :class:`ChangeRequestEvent` row (from/to/actor/payload)
— this append-only log is the reconciler's recovery record after a crash. The
legal-transition table below is the single source of truth; an illegal
transition raises :class:`IllegalTransition` (mapped to 409 at the API).

This module owns the create/approve/reject transitions and the shared
transition primitive. The apply/confirm transitions (applying →
awaiting_confirm → applied, → failed) live in ``change_apply`` but reuse
:func:`record_transition` so every state change is logged uniformly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.change_request import ChangeRequest
from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus as S
from northbound.models.user import User
from northbound.schemas.driver import L3Change, OspfChange, PortChange, VlanChange, VrfChange
from northbound.services import audit, port_state
from northbound.services.device_policy import assert_writable

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

# Legal transitions: from_status -> set of permitted to_status.
_LEGAL: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.APPROVED, S.REJECTED, S.APPLYING, S.NEEDS_REVISION}),
    # Requester resubmits (→ PENDING) or it's rejected outright. NEEDS_REVISION is
    # NOT terminal — that's what makes the review loop two-way.
    S.NEEDS_REVISION: frozenset({S.PENDING, S.REJECTED}),
    S.APPROVED: frozenset({S.APPLYING, S.REJECTED}),
    S.APPLYING: frozenset({S.AWAITING_CONFIRM, S.APPLIED, S.FAILED}),
    S.AWAITING_CONFIRM: frozenset({S.APPLIED, S.FAILED, S.REVERTED}),
    # Terminal states — no outgoing transitions.
    S.APPLIED: frozenset(),
    S.FAILED: frozenset(),
    S.REJECTED: frozenset(),
    S.REVERTED: frozenset(),
}


class RequestError(Exception):
    """Base class for change-request workflow failures."""


class IllegalTransition(RequestError):
    """Attempted a status transition the state machine forbids."""

    def __init__(self, from_status: S, to_status: S) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"illegal transition {from_status.value} -> {to_status.value}")


class AlreadyClaimed(RequestError):
    """A concurrent worker already moved the request out of the expected state.

    Raised by :func:`claim_transition` when the atomic conditional UPDATE matches
    zero rows — i.e. another coroutine/worker won the race to advance this row.
    The loser must NOT perform any device I/O. The route maps this to 409.
    """

    def __init__(self, request_id: str, expected: Iterable[S], to_status: S) -> None:
        self.request_id = request_id
        self.expected = frozenset(expected)
        self.to_status = to_status
        names = ", ".join(sorted(s.value for s in self.expected))
        super().__init__(
            f"request {request_id} could not be claimed for {to_status.value}: "
            f"no longer in {{{names}}} (another worker advanced it)"
        )


def can_transition(from_status: S, to_status: S) -> bool:
    return to_status in _LEGAL.get(from_status, frozenset())


async def record_transition(
    session: AsyncSession,
    request: ChangeRequest,
    *,
    to_status: S,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Validate + apply a status transition and append a ChangeRequestEvent.

    Raises :class:`IllegalTransition` if the move is not in the table. The
    event row is the reconciler's recovery log (D3) — written for every move.
    """
    from_status = request.status
    if not can_transition(from_status, to_status):
        raise IllegalTransition(from_status, to_status)
    request.status = to_status
    session.add(request)
    session.add(
        ChangeRequestEvent(
            request_id=request.id,
            from_status=from_status.value,
            to_status=to_status.value,
            actor=actor,
            payload=payload,
        )
    )
    await session.flush()


async def claim_transition(
    session: AsyncSession,
    request: ChangeRequest,
    *,
    expected: Iterable[S],
    to_status: S,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Atomically claim ``request`` for ``to_status`` and log the transition.

    This is the AUTHORITATIVE serialization point for state moves that gate
    device I/O (approved→applying, the awaiting_confirm→{applied,reverted,failed}
    fork). It issues a single conditional ``UPDATE ... WHERE id=:id AND status IN
    (:expected)`` and checks ``rowcount``:

      * ``rowcount == 1`` → this caller won the claim. The in-memory object is
        synced and a :class:`ChangeRequestEvent` is appended (event log unchanged
        in shape — same rows record_transition writes). The caller may proceed to
        device I/O.
      * ``rowcount == 0`` → another worker already advanced the row; we raise
        :class:`AlreadyClaimed` WITHOUT touching the driver.

    Portability: the conditional UPDATE works identically on SQLite and Postgres
    (no ``FOR UPDATE`` needed). The ``version_id`` column (bumped here via the
    explicit ``+1`` so the ORM's optimistic counter stays consistent) is the
    backstop: a stale in-memory copy that later flushes raises ``StaleDataError``.

    The transition must still be legal per the state machine — every value in
    ``expected`` must permit ``to_status`` — otherwise :class:`IllegalTransition`
    is raised before any DB write (programmer-error guard).
    """
    expected_set = frozenset(expected)
    for from_status_candidate in expected_set:
        if not can_transition(from_status_candidate, to_status):
            raise IllegalTransition(from_status_candidate, to_status)

    # Capture the pre-claim status for the event log before the raw UPDATE.
    from_status = request.status

    # Flush any pending ORM mutations on this object FIRST, so the upcoming raw
    # UPDATE does not race the ORM's own versioned UPDATE on the same row.
    await session.flush()

    result = await session.execute(
        update(ChangeRequest)
        .where(
            ChangeRequest.id == request.id,
            ChangeRequest.status.in_(list(expected_set)),
        )
        .values(status=to_status, version_id=ChangeRequest.version_id + 1)
        .execution_options(synchronize_session=False)
    )
    # ``execute(UPDATE ...)`` returns a CursorResult; rowcount is the count of
    # rows the WHERE matched (1 = we claimed it, 0 = someone else did).
    if cast(CursorResult[Any], result).rowcount != 1:
        raise AlreadyClaimed(request.id, expected_set, to_status)

    # The raw UPDATE bumped status + version_id in the DB out of band, so the
    # ORM's cached attributes (incl. its optimistic version counter) are stale.
    # Refresh re-reads them, keeping any later ORM flush's versioned UPDATE from
    # mismatching the DB row and raising a spurious StaleDataError.
    await session.refresh(request)

    session.add(
        ChangeRequestEvent(
            request_id=request.id,
            from_status=from_status.value,
            to_status=to_status.value,
            actor=actor,
            payload=payload,
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# Create / approve / reject
# ---------------------------------------------------------------------------


async def create_request(
    session: AsyncSession,
    *,
    device: Device,
    port_name: str,
    requested_changes: PortChange,
    reason: str,
    user: User,
) -> ChangeRequest:
    """File a change request. Fails fast (403) on a read-only target (F50/F60).

    Captures the device's current ``device_state_fingerprint`` at file time so
    the apply flow can detect drift. Writes an audit entry. Status = pending.
    """
    # Fail fast: never accept a request against a read-only device.
    assert_writable(device)

    fingerprint = await port_state.current_fingerprint(device, refresh=True)

    request = ChangeRequest(
        device_id=device.id,
        port_name=port_name,
        requested_by=user.id,
        requested_changes=requested_changes.model_dump(exclude_none=False),
        reason=reason,
        status=S.PENDING,
        device_state_fingerprint=fingerprint,
    )
    session.add(request)
    await session.flush()

    session.add(
        ChangeRequestEvent(
            request_id=request.id,
            from_status="",
            to_status=S.PENDING.value,
            actor=user.id,
            payload={"reason": reason},
        )
    )
    await audit.append_audit(
        session,
        user_id=user.id,
        action="request.created",
        target_device_id=device.id,
        target_port=port_name,
        after={"requested_changes": request.requested_changes, "reason": reason},
        result="ok",
    )
    await session.flush()
    return request


async def create_vlan_request(
    session: AsyncSession,
    *,
    device: Device,
    change: VlanChange,
    reason: str,
    user: User,
) -> ChangeRequest:
    """File a VLAN-database change request (create/delete a VLAN id).

    Device-level (no port target): ``port_name`` is empty and the change kind is
    tagged into ``requested_changes`` as ``_kind="vlan"`` so the apply flow renders
    it via ``driver.render_vlan_change``. Fails fast (403) on a read-only device.
    """
    assert_writable(device)
    fingerprint = await port_state.current_fingerprint(device, refresh=True)

    request = ChangeRequest(
        device_id=device.id,
        port_name="",  # device-level change, not a switchport
        requested_by=user.id,
        requested_changes={"_kind": "vlan", **change.model_dump()},
        reason=reason,
        status=S.PENDING,
        device_state_fingerprint=fingerprint,
    )
    session.add(request)
    await session.flush()

    session.add(
        ChangeRequestEvent(
            request_id=request.id,
            from_status="",
            to_status=S.PENDING.value,
            actor=user.id,
            payload={"reason": reason, "kind": "vlan"},
        )
    )
    await audit.append_audit(
        session,
        user_id=user.id,
        action="request.created",
        target_device_id=device.id,
        target_port=f"vlan:{change.vlan_id}",
        after={"requested_changes": request.requested_changes, "reason": reason},
        result="ok",
    )
    await session.flush()
    return request


async def create_ospf_request(
    session: AsyncSession,
    *,
    device: Device,
    change: OspfChange,
    reason: str,
    user: User,
) -> ChangeRequest:
    """File an OSPF config-change request (device-level; ``_kind="ospf"``)."""
    assert_writable(device)
    fingerprint = await port_state.current_fingerprint(device, refresh=True)
    target = change.interface if change.target == "interface" else "router-id"
    request = ChangeRequest(
        device_id=device.id,
        port_name="",
        requested_by=user.id,
        requested_changes={"_kind": "ospf", **change.model_dump()},
        reason=reason,
        status=S.PENDING,
        device_state_fingerprint=fingerprint,
    )
    session.add(request)
    await session.flush()
    session.add(
        ChangeRequestEvent(
            request_id=request.id,
            from_status="",
            to_status=S.PENDING.value,
            actor=user.id,
            payload={"reason": reason, "kind": "ospf"},
        )
    )
    await audit.append_audit(
        session,
        user_id=user.id,
        action="request.created",
        target_device_id=device.id,
        target_port=f"ospf:{target}",
        after={"requested_changes": request.requested_changes, "reason": reason},
        result="ok",
    )
    await session.flush()
    return request


async def create_vrf_request(
    session: AsyncSession,
    *,
    device: Device,
    change: VrfChange,
    reason: str,
    user: User,
) -> ChangeRequest:
    """File a VRF create/delete request (device-level; ``_kind="vrf"``)."""
    assert_writable(device)
    fingerprint = await port_state.current_fingerprint(device, refresh=True)
    request = ChangeRequest(
        device_id=device.id,
        port_name="",
        requested_by=user.id,
        requested_changes={"_kind": "vrf", **change.model_dump()},
        reason=reason,
        status=S.PENDING,
        device_state_fingerprint=fingerprint,
    )
    session.add(request)
    await session.flush()
    session.add(
        ChangeRequestEvent(
            request_id=request.id,
            from_status="",
            to_status=S.PENDING.value,
            actor=user.id,
            payload={"reason": reason, "kind": "vrf"},
        )
    )
    await audit.append_audit(
        session,
        user_id=user.id,
        action="request.created",
        target_device_id=device.id,
        target_port=f"vrf:{change.name}",
        after={"requested_changes": request.requested_changes, "reason": reason},
        result="ok",
    )
    await session.flush()
    return request


async def create_l3_request(
    session: AsyncSession,
    *,
    device: Device,
    change: L3Change,
    reason: str,
    user: User,
) -> ChangeRequest:
    """File a routed-interface change request (SVI / loopback create or delete).

    Device-level (``port_name=""``); the L3 intent is tagged into
    ``requested_changes`` as ``_kind="l3"`` so apply renders it via
    ``driver.render_l3_change``. Fails fast (403) on a read-only device."""
    assert_writable(device)
    fingerprint = await port_state.current_fingerprint(device, refresh=True)

    request = ChangeRequest(
        device_id=device.id,
        port_name="",
        requested_by=user.id,
        requested_changes={"_kind": "l3", **change.model_dump()},
        reason=reason,
        status=S.PENDING,
        device_state_fingerprint=fingerprint,
    )
    session.add(request)
    await session.flush()

    session.add(
        ChangeRequestEvent(
            request_id=request.id,
            from_status="",
            to_status=S.PENDING.value,
            actor=user.id,
            payload={"reason": reason, "kind": "l3"},
        )
    )
    await audit.append_audit(
        session,
        user_id=user.id,
        action="request.created",
        target_device_id=device.id,
        target_port=change.iface_name,
        after={"requested_changes": request.requested_changes, "reason": reason},
        result="ok",
    )
    await session.flush()
    return request


async def approve_request(
    session: AsyncSession,
    request: ChangeRequest,
    reviewer: User,
) -> ChangeRequest:
    """pending → approved. Records reviewer + audit entry."""

    await record_transition(session, request, to_status=S.APPROVED, actor=reviewer.id)
    request.reviewer_id = reviewer.id
    request.reviewed_at = dt.datetime.now(tz=dt.UTC)
    session.add(request)
    await audit.append_audit(
        session,
        user_id=reviewer.id,
        action="request.approved",
        target_device_id=request.device_id,
        target_port=request.port_name,
        result="ok",
    )
    await session.flush()
    return request


async def reject_request(
    session: AsyncSession,
    request: ChangeRequest,
    reviewer: User,
    comment: str,
) -> ChangeRequest:
    """pending → rejected. ``comment`` is required (non-empty)."""

    if not comment or not comment.strip():
        raise RequestError("a rejection comment is required")

    await record_transition(
        session,
        request,
        to_status=S.REJECTED,
        actor=reviewer.id,
        payload={"comment": comment},
    )
    request.reviewer_id = reviewer.id
    request.reviewer_comment = comment
    request.reviewed_at = dt.datetime.now(tz=dt.UTC)
    session.add(request)
    await audit.append_audit(
        session,
        user_id=reviewer.id,
        action="request.rejected",
        target_device_id=request.device_id,
        target_port=request.port_name,
        after={"comment": comment},
        result="ok",
    )
    await session.flush()
    return request


async def request_changes(
    session: AsyncSession,
    request: ChangeRequest,
    reviewer: User,
    comment: str,
) -> ChangeRequest:
    """pending → needs_revision. Admin asks the requester to revise instead of a
    hard reject; ``comment`` (what to change / why) is required."""
    if not comment or not comment.strip():
        raise RequestError("a comment explaining the requested changes is required")

    await record_transition(
        session,
        request,
        to_status=S.NEEDS_REVISION,
        actor=reviewer.id,
        payload={"comment": comment},
    )
    request.reviewer_id = reviewer.id
    request.reviewer_comment = comment
    request.reviewed_at = dt.datetime.now(tz=dt.UTC)
    session.add(request)
    await audit.append_audit(
        session,
        user_id=reviewer.id,
        action="request.changes_requested",
        target_device_id=request.device_id,
        target_port=request.port_name,
        after={"comment": comment},
        result="ok",
    )
    await session.flush()
    return request


async def resubmit_request(
    session: AsyncSession,
    request: ChangeRequest,
    requester: User,
    *,
    device: Device,
    requested_changes: PortChange | None = None,
    reason: str | None = None,
) -> ChangeRequest:
    """needs_revision → pending. The owner revises and resubmits for review.

    If ``requested_changes`` is supplied the request is updated and its drift
    fingerprint is re-captured (the device may have moved on while in revision).
    """
    assert_writable(device)
    if requested_changes is not None:
        request.requested_changes = requested_changes.model_dump(exclude_none=False)
        request.device_state_fingerprint = await port_state.current_fingerprint(
            device, refresh=True
        )
    if reason is not None:
        request.reason = reason

    await record_transition(
        session,
        request,
        to_status=S.PENDING,
        actor=requester.id,
        payload={"resubmitted": True},
    )
    # Back in the queue: the prior review is superseded (the admin's note stays
    # on the row + in the event log as history).
    request.reviewed_at = None
    session.add(request)
    await audit.append_audit(
        session,
        user_id=requester.id,
        action="request.resubmitted",
        target_device_id=request.device_id,
        target_port=request.port_name,
        after={"requested_changes": request.requested_changes, "reason": request.reason},
        result="ok",
    )
    await session.flush()
    return request


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def list_requests(
    session: AsyncSession,
    *,
    mine_user_id: str | None = None,
    status: S | None = None,
) -> list[ChangeRequest]:
    """List requests, newest first, with optional requester / status filters."""
    stmt = select(ChangeRequest).order_by(ChangeRequest.created_at.desc())
    if mine_user_id is not None:
        stmt = stmt.where(ChangeRequest.requested_by == mine_user_id)
    if status is not None:
        stmt = stmt.where(ChangeRequest.status == status)
    rows = await session.scalars(stmt)
    return list(rows.all())


async def get_request(session: AsyncSession, request_id: str) -> ChangeRequest | None:
    return await session.scalar(select(ChangeRequest).where(ChangeRequest.id == request_id))


async def add_comment(
    session: AsyncSession, request: ChangeRequest, user: User, body: str
) -> ChangeRequestEvent:
    """Append a free-text comment to a request's event log (no status change).

    A comment is a ChangeRequestEvent with from==to (current status) and
    ``payload={"kind":"comment","body":...}`` — so the request timeline is one
    ordered stream of transitions + comments (GitHub-PR style)."""
    event = ChangeRequestEvent(
        request_id=request.id,
        from_status=request.status.value,
        to_status=request.status.value,
        actor=user.id,
        payload={"kind": "comment", "body": body},
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(session: AsyncSession, request_id: str) -> list[ChangeRequestEvent]:
    """The full event log for a request (transitions + comments), oldest first."""
    rows = await session.scalars(
        select(ChangeRequestEvent)
        .where(ChangeRequestEvent.request_id == request_id)
        .order_by(ChangeRequestEvent.created_at)
    )
    return list(rows.all())


async def usernames_for(session: AsyncSession, user_ids: set[str]) -> dict[str, str]:
    """Map user id → username for the given ids in ONE query (avoids N+1 when
    serializing a list of requests). Missing ids are simply absent from the map."""
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}
