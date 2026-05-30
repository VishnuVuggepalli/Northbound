"""Apply flow — the critical path (principal-engineering D3/D4 + drift guard).

``apply_request`` drives a change from ``approved`` (or ``pending`` via the
admin approve+apply shortcut) through the persisted state machine to either
``awaiting_confirm`` (commit-confirm platforms) or ``applied`` (no native
confirm), or ``failed`` on any driver error.

Crash-safety: status, ``confirm_token`` and ``confirm_deadline_at`` are
persisted on the ChangeRequest row *before* control returns. A process crash
mid-apply leaves a row in ``applying`` or ``awaiting_confirm``; the reconciler
(NEXT WAVE) reads those rows and resumes — confirms within the window or reverts
past the deadline. This module exposes :func:`confirm_request` for the manual /
reconciler confirm path; the deadline-revert loop itself is the reconciler's job.

Stale-state drift guard (D-drift): the device fingerprint captured at request
file time is re-checked against live state at apply time. A mismatch blocks the
apply (status unchanged) and raises :class:`StateDrift` so an admin must
re-confirm against the new reality.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from northbound.config import get_settings
from northbound.drivers.base import DriverError
from northbound.drivers.factory import driver_for
from northbound.models.change_request import ChangeRequest
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.enums import ChangeRequestStatus as S
from northbound.models.user import User
from northbound.schemas.driver import Credentials, PortChange
from northbound.services import audit, port_state, requests
from northbound.services.credvault import FernetCredVault, deserialize_credentials
from northbound.services.device_policy import assert_writable


class ApplyError(Exception):
    """Base class for apply-flow failures."""


class StateDrift(ApplyError):
    """Live device state diverged from the fingerprint captured at file time."""

    def __init__(self, expected: str | None, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__("device state changed since the request was filed")


class ApplyFailed(ApplyError):
    """The driver rejected the change; the request is now ``failed``."""


def _credentials_for(device: Device) -> Credentials:
    if device.encrypted_credentials is None:
        return Credentials()
    vault = FernetCredVault.from_settings()
    return deserialize_credentials(device.encrypted_credentials, vault)


async def apply_request(
    session: AsyncSession,
    request: ChangeRequest,
    device: Device,
    user: User,
) -> ChangeRequest:
    """Execute the apply flow for an approved (or pending) request.

    Returns the updated request. On commit-confirm platforms the request ends
    in ``awaiting_confirm`` carrying ``confirm_token`` + ``confirm_deadline_at``.
    On platforms without native confirm it ends in ``applied``. On a driver
    error it ends in ``failed`` and :class:`ApplyFailed` is raised.
    """
    # 1. Verify the request is in an applyable state (approved, or pending via
    #    the admin approve+apply shortcut). record_transition enforces legality.
    if request.status not in (S.APPROVED, S.PENDING):
        raise ApplyError(f"request is {request.status.value}; only approved/pending can be applied")

    # 2. Re-check writability (defense in depth; create_request already did).
    assert_writable(device)

    # 3. Load creds + driver.
    creds = _credentials_for(device)
    driver = driver_for(device, creds)

    # 4. Stale-state guard: recompute the live fingerprint and compare.
    live_fingerprint = await port_state.current_fingerprint(device, refresh=True)
    if (
        request.device_state_fingerprint is not None
        and live_fingerprint != request.device_state_fingerprint
    ):
        # Block: status stays as-is, no event/audit beyond the drift record.
        await audit.append_audit(
            session,
            user_id=user.id,
            action="request.apply_blocked_drift",
            target_device_id=device.id,
            target_port=request.port_name,
            before={"fingerprint": request.device_state_fingerprint},
            after={"fingerprint": live_fingerprint},
            result="blocked",
        )
        await session.flush()
        raise StateDrift(request.device_state_fingerprint, live_fingerprint)

    # 5. status -> applying (+ event).
    await requests.record_transition(session, request, to_status=S.APPLYING, actor=user.id)

    change = PortChange(**request.requested_changes)

    try:
        # 6. Backup current config.
        backup_text = await driver.backup_config()
        session.add(
            ConfigBackup(
                device_id=device.id,
                config_text=backup_text,
                fetched_at=dt.datetime.now(tz=dt.UTC),
                fetched_by=user.id,
            )
        )
        await session.flush()

        # 7. Render the change, persist the diff text.
        diff = await driver.render_change(request.port_name, change)
        request.diff_text = diff.raw_after
        session.add(request)
        await session.flush()

        # 8. Apply with commit-confirm window.
        confirm_seconds = get_settings().commit_confirm_seconds
        result = await driver.apply_change(diff, confirm_seconds=confirm_seconds)
    except DriverError as exc:
        # 12. Driver error → failed (+ event + audit), re-raise for a 502.
        await requests.record_transition(
            session,
            request,
            to_status=S.FAILED,
            actor=user.id,
            payload={"error": str(exc)},
        )
        await audit.append_audit(
            session,
            user_id=user.id,
            action="request.apply_failed",
            target_device_id=device.id,
            target_port=request.port_name,
            after={"error": str(exc)},
            result="error",
        )
        await session.flush()
        raise ApplyFailed(str(exc)) from exc

    if not result.success:
        await requests.record_transition(
            session,
            request,
            to_status=S.FAILED,
            actor=user.id,
            payload={"error": result.error},
        )
        await audit.append_audit(
            session,
            user_id=user.id,
            action="request.apply_failed",
            target_device_id=device.id,
            target_port=request.port_name,
            after={"error": result.error},
            result="error",
        )
        await session.flush()
        raise ApplyFailed(result.error or "apply reported failure")

    # 9. Audit the apply (before/after = rendered diff summary, NEVER creds).
    await audit.append_audit(
        session,
        user_id=user.id,
        action="request.applied",
        target_device_id=device.id,
        target_port=request.port_name,
        before={"summary": diff.summary},
        after={"commands": list(diff.commands)},
        result="ok",
    )

    # Live state changed on the device — drop the cache so the next read refetches.
    port_state.invalidate(device.id)

    if result.confirm_token:
        # 10. Commit-confirm platform → awaiting_confirm; persist token + deadline.
        request.confirm_token = result.confirm_token
        request.confirm_deadline_at = result.confirm_deadline_at
        session.add(request)
        await requests.record_transition(
            session,
            request,
            to_status=S.AWAITING_CONFIRM,
            actor=user.id,
            payload={"confirm_deadline_at": result.confirm_deadline_at},
        )
    else:
        # 11. No native confirm → applied directly.
        request.applied_at = dt.datetime.now(tz=dt.UTC)
        session.add(request)
        await requests.record_transition(session, request, to_status=S.APPLIED, actor=user.id)

    await session.flush()
    return request


async def confirm_request(
    session: AsyncSession,
    request: ChangeRequest,
    device: Device,
    user: User,
) -> ChangeRequest:
    """awaiting_confirm → applied. Calls ``driver.confirm(token)``; audits.

    The reconciler (NEXT WAVE) calls this same path on the confirm-window logic;
    here it is exposed for the manual admin confirm button.
    """
    if request.status != S.AWAITING_CONFIRM:
        raise ApplyError(
            f"request is {request.status.value}; only awaiting_confirm can be confirmed"
        )
    if not request.confirm_token:
        raise ApplyError("request has no confirm token")

    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        await driver.confirm(request.confirm_token)
    except DriverError as exc:
        await audit.append_audit(
            session,
            user_id=user.id,
            action="request.confirm_failed",
            target_device_id=device.id,
            target_port=request.port_name,
            after={"error": str(exc)},
            result="error",
        )
        await session.flush()
        raise ApplyFailed(str(exc)) from exc

    request.applied_at = dt.datetime.now(tz=dt.UTC)
    request.confirm_token = None
    request.confirm_deadline_at = None
    session.add(request)
    await requests.record_transition(session, request, to_status=S.APPLIED, actor=user.id)
    await audit.append_audit(
        session,
        user_id=user.id,
        action="request.confirmed",
        target_device_id=device.id,
        target_port=request.port_name,
        result="ok",
    )
    await session.flush()
    return request
