"""Reconciler loop — crash + deadline recovery (principal-engineering D3/D4).

The apply flow (:mod:`northbound.services.change_apply`) persists every state
transition to the DB *before* control returns, so an in-flight change is always
recoverable from rows alone. The reconciler is the recovery half: it runs every
``reconciler_interval_seconds`` (D4: 10s) and resolves requests stuck in a
non-terminal in-flight state after a crash or a missed commit-confirm window.

Decision table (in-flight state x condition -> action):

    awaiting_confirm + deadline past now   → failed  ("auto-reverted: confirm
                                              window expired"). The DEVICE
                                              self-reverts at its own commit
                                              timer (Arista session timer, Pica8
                                              confirmed-commit), so we do NOT
                                              call driver.confirm. We DEFENSIVELY
                                              call driver.revert(token) in a try
                                              for platforms that need an explicit
                                              abort — failure there is logged,
                                              never fatal.
    awaiting_confirm + deadline not past   → untouched (still inside the window;
                                              operator may yet confirm).
    applying + latest event is stale       → failed  ("interrupted: process
                                              restart during apply; manual
                                              review required"). Crash mid-apply.
                                              We do NOT auto-retry apply — see
                                              "Why no auto-retry" below.
    applying + latest event is fresh        → untouched (an apply is genuinely
                                              in progress in another coroutine).
    any terminal state                      → not selected by the query at all.

Idempotency: the only writes are ``record_transition`` (guarded by the legal
state machine — a second pass finds the row already terminal and the query
skips it) and ``append_audit``. Running :func:`reconcile_once` twice over the
same data produces exactly one failure per affected request, not two.

Why no auto-retry on ``applying``: a crash can land *after* the device applied
the change but *before* the DB recorded the transition. Re-issuing apply would
double-apply (e.g. a second commit, a stacked config session) with no way to
know which side committed. The conservative, trust-preserving move is to fail
the request and surface it for a human, who can read the device and decide.

Platform self-revert vs explicit revert call:
  - arista  — session commit-timer auto-reverts on the device; explicit
              ``revert`` (abort/rollback) is a belt-and-braces cleanup.
  - pica8   — NETCONF confirmed-commit auto-reverts on the device; same.
  - mock    — ``revert`` just drops the token (no-op device side).
  - mikrotik/freebsd — never enter awaiting_confirm (no native commit-confirm).
The defensive ``revert`` is wrapped so a platform that does not need it (or
whose session already expired) cannot turn cleanup into a job crash.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.config import get_settings
from northbound.db import async_session_factory
from northbound.drivers.factory import driver_for
from northbound.models.change_request import ChangeRequest
from northbound.models.change_request_event import ChangeRequestEvent
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus as S
from northbound.schemas.driver import Credentials
from northbound.services import audit, requests
from northbound.services.credvault import FernetCredVault, deserialize_credentials

logger = logging.getLogger("northbound.services.reconciler")

# The reconciler acts on the system's behalf — not a logged-in user. This actor
# id is recorded in transition events and audit rows so the recovery action is
# attributable but distinct from any human.
SYSTEM_ACTOR = "system:reconciler"

# Non-terminal in-flight states the reconciler is responsible for.
_IN_FLIGHT: frozenset[S] = frozenset({S.AWAITING_CONFIRM, S.APPLYING})

_CONFIRM_EXPIRED_REASON = "auto-reverted: confirm window expired"
_INTERRUPTED_REASON = "interrupted: process restart during apply; manual review required"


def _credentials_for(device: Device) -> Credentials:
    if device.encrypted_credentials is None:
        return Credentials()
    vault = FernetCredVault.from_settings()
    return deserialize_credentials(device.encrypted_credentials, vault)


async def _latest_event_at(
    session: AsyncSession,
    request_id: str,
) -> dt.datetime | None:
    """Timestamp of the most recent transition event for a request."""
    return await session.scalar(
        select(ChangeRequestEvent.created_at)
        .where(ChangeRequestEvent.request_id == request_id)
        .order_by(desc(ChangeRequestEvent.created_at))
        .limit(1)
    )


def _aware(value: dt.datetime) -> dt.datetime:
    """Normalize a possibly-naive DB datetime to UTC-aware for comparison.

    SQLite round-trips ``DateTime(timezone=True)`` as naive; we attach UTC so
    the staleness comparison against an aware ``now`` never raises.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


async def _fail_confirm_expired(
    session: AsyncSession,
    request: ChangeRequest,
) -> None:
    """awaiting_confirm past deadline → failed. Device self-reverts; we record.

    Defensively calls ``driver.revert(token)`` for platforms that need an
    explicit abort. Any driver error there is logged, not propagated.
    """
    token = request.confirm_token
    device = await session.get(Device, request.device_id)
    if device is not None and token:
        try:
            driver = driver_for(device, _credentials_for(device))
            await driver.revert(token)
        except Exception as exc:
            logger.warning(
                "reconciler: defensive revert failed for request %s (token=%s): %s",
                request.id,
                token,
                exc,
            )

    request.confirm_token = None
    request.confirm_deadline_at = None
    session.add(request)
    await requests.record_transition(
        session,
        request,
        to_status=S.FAILED,
        actor=SYSTEM_ACTOR,
        payload={"reason": _CONFIRM_EXPIRED_REASON},
    )
    await audit.append_audit(
        session,
        user_id=None,
        action="request.auto_reverted",
        target_device_id=request.device_id,
        target_port=request.port_name,
        after={"reason": _CONFIRM_EXPIRED_REASON},
        result="reverted",
    )
    logger.warning(
        "reconciler: request %s failed — %s",
        request.id,
        _CONFIRM_EXPIRED_REASON,
    )


async def _fail_interrupted(
    session: AsyncSession,
    request: ChangeRequest,
) -> None:
    """applying + stale → failed for human review. Never auto-retried."""
    await requests.record_transition(
        session,
        request,
        to_status=S.FAILED,
        actor=SYSTEM_ACTOR,
        payload={"reason": _INTERRUPTED_REASON},
    )
    await audit.append_audit(
        session,
        user_id=None,
        action="request.interrupted",
        target_device_id=request.device_id,
        target_port=request.port_name,
        after={"reason": _INTERRUPTED_REASON},
        result="error",
    )
    logger.warning(
        "reconciler: request %s failed — %s",
        request.id,
        _INTERRUPTED_REASON,
    )


async def reconcile_once(
    session: AsyncSession,
    *,
    now: dt.datetime,
    apply_stale_seconds: int | None = None,
) -> int:
    """Resolve in-flight requests stuck after a crash or missed confirm window.

    ``now`` is injected for determinism (tests pass a fixed instant). Returns
    the number of requests transitioned to ``failed`` this pass — 0 when there
    is nothing to do, which makes idempotency observable.

    Idempotent: only non-terminal in-flight rows are selected, and the only
    mutations are legal terminal transitions + audit appends. A second call
    over the same data finds the affected rows already terminal (excluded by
    the query) → returns 0.
    """
    stale_seconds = (
        apply_stale_seconds
        if apply_stale_seconds is not None
        else get_settings().reconciler_apply_stale_seconds
    )
    now_epoch = now.timestamp()
    stale_cutoff = now - dt.timedelta(seconds=stale_seconds)

    rows = (
        await session.scalars(select(ChangeRequest).where(ChangeRequest.status.in_(_IN_FLIGHT)))
    ).all()

    failed = 0
    for request in rows:
        if request.status == S.AWAITING_CONFIRM:
            deadline = request.confirm_deadline_at
            if deadline is not None and deadline <= now_epoch:
                await _fail_confirm_expired(session, request)
                failed += 1
            # else: still inside the window — leave untouched.
        elif request.status == S.APPLYING:
            last_event = await _latest_event_at(session, request.id)
            if last_event is None or _aware(last_event) <= stale_cutoff:
                await _fail_interrupted(session, request)
                failed += 1
            # else: an apply is genuinely in progress — leave untouched.

    await session.flush()
    return failed


async def reconciler_tick() -> None:
    """Scheduler entry point: open a session, reconcile, commit, close.

    Opens its OWN session from ``async_session_factory`` (never a request-scoped
    one). Any exception is caught and logged so a single bad tick can never kill
    the scheduler (hard rule 3).
    """
    try:
        async with async_session_factory() as session:
            try:
                count = await reconcile_once(session, now=dt.datetime.now(tz=dt.UTC))
                await session.commit()
                if count:
                    logger.info("reconciler tick: resolved %d in-flight request(s)", count)
            except Exception:
                await session.rollback()
                raise
    except Exception:
        logger.exception("reconciler tick failed; scheduler continues")
