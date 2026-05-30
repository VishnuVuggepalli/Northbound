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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.change_request import ChangeRequest
from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus as S
from northbound.models.user import User
from northbound.schemas.driver import PortChange
from northbound.services import audit, port_state
from northbound.services.device_policy import assert_writable

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

# Legal transitions: from_status -> set of permitted to_status.
_LEGAL: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.APPROVED, S.REJECTED, S.APPLYING}),
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
