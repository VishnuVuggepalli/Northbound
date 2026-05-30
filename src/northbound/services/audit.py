"""Audit log — append-only, tamper-evident hash chain (principal-engineering D6).

Each row carries ``row_hash = sha256(prev_hash + canonical_json(row))`` where
``row`` excludes the hash columns themselves. The first row's ``prev_hash`` is
the genesis marker :data:`GENESIS`. Any later mutation/deletion breaks the
chain, which :func:`verify_chain` detects.

Hard rules:
- Append-only. This module never UPDATEs or DELETEs an audit row.
- Credentials are never stored. Callers must redact ``before``/``after``; for
  cred-related actions, record the action name only (no value). :func:`append_audit`
  additionally strips any obviously-secret keys as a defense-in-depth backstop.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.audit_log import AuditLog

GENESIS = "GENESIS"

# Defense-in-depth: keys whose values must never land in audit JSON. Callers
# are expected to redact upstream; this is a backstop, not the primary guard.
_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "ssh_private_key",
        "api_token",
        "snmp_community",
        "snmp_v3_auth_key",
        "snmp_v3_priv_key",
        "secret",
        "credentials",
        "encrypted_credentials",
    }
)

_REDACTED = "[REDACTED]"


def _redact(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Recursively replace secret-keyed values with a redaction marker."""
    if value is None:
        return None
    out: dict[str, Any] = {}
    for key, val in value.items():
        if key.lower() in _SECRET_KEYS:
            out[key] = _REDACTED
        elif isinstance(val, dict):
            out[key] = _redact(val)  # type: ignore[arg-type]  # nested mapping
        else:
            out[key] = val
    return out


def _canonical_json(payload: dict[str, Any]) -> str:
    """Stable JSON: sorted keys, no whitespace. The chain depends on this."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)


def _ts_key(created_at: dt.datetime) -> str:
    """Canonical timestamp string for hashing.

    SQLite's ``DateTime(timezone=True)`` round-trips a tz-aware value as a
    *naive* datetime on read, so a raw ``.isoformat()`` would differ between
    the append-time (aware) and verify-time (naive) values and break the chain.
    We strip tzinfo to a stable microsecond ISO string so both sides agree.
    """
    return created_at.replace(tzinfo=None).isoformat()


def compute_row_hash(
    *,
    prev_hash: str,
    user_id: str | None,
    action: str,
    target_device_id: str | None,
    target_port: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    result: str,
    created_at: dt.datetime,
) -> str:
    """sha256 over ``prev_hash`` + the canonical JSON of the chained fields.

    ``created_at`` is included so reordering rows breaks the chain. ``id`` is
    deliberately excluded (random UUID, not chain-relevant).
    """
    body = {
        "action": action,
        "after": after,
        "before": before,
        "created_at": _ts_key(created_at),
        "result": result,
        "target_device_id": target_device_id,
        "target_port": target_port,
        "user_id": user_id,
    }
    digest_input = prev_hash + _canonical_json(body)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


async def _latest_hash(session: AsyncSession) -> str:
    """Return the most-recent row's ``row_hash`` (chain tip), or GENESIS."""
    # Order by created_at then id so the tip is deterministic even when two rows
    # share a timestamp (SQLite second-resolution server default).
    tip = await session.scalar(
        select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(1)
    )
    if tip is None or not tip.row_hash:
        return GENESIS
    return tip.row_hash


async def append_audit(
    session: AsyncSession,
    *,
    user_id: str | None,
    action: str,
    target_device_id: str | None = None,
    target_port: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    result: str = "ok",
) -> AuditLog:
    """Append one hash-chained audit row. Never stores plaintext credentials.

    The row is added + flushed (so ``id`` and ``created_at`` are populated) but
    NOT committed — the caller's transaction owns the commit boundary.
    """
    safe_before = _redact(before)
    safe_after = _redact(after)
    prev_hash = await _latest_hash(session)

    # Stamp created_at explicitly with microsecond precision (UTC), overriding
    # the second-resolution server default. This gives a near-unique, monotonic
    # ordering key so the chain's tip query and verify walk agree even on rows
    # inserted within the same wall-clock second.
    created = dt.datetime.now(tz=dt.UTC)

    row = AuditLog(
        user_id=user_id,
        action=action,
        target_device_id=target_device_id,
        target_port=target_port,
        before=safe_before,
        after=safe_after,
        result=result,
        row_hash="",  # filled after we know created_at
        prev_hash=prev_hash,
        created_at=created,
    )
    session.add(row)
    await session.flush()

    row.row_hash = compute_row_hash(
        prev_hash=prev_hash,
        user_id=user_id,
        action=action,
        target_device_id=target_device_id,
        target_port=target_port,
        before=safe_before,
        after=safe_after,
        result=result,
        created_at=row.created_at,
    )
    await session.flush()
    return row


def _recompute(row: AuditLog, prev_hash: str) -> str:
    return compute_row_hash(
        prev_hash=prev_hash,
        user_id=row.user_id,
        action=row.action,
        target_device_id=row.target_device_id,
        target_port=row.target_port,
        before=row.before,
        after=row.after,
        result=row.result,
        created_at=row.created_at,
    )


async def verify_chain(session: AsyncSession) -> tuple[bool, int | None]:
    """Walk the chain in order; recompute and compare every row's hash.

    Returns ``(True, None)`` if intact, else ``(False, index)`` where ``index``
    is the 0-based position of the first row that fails to verify (either a
    mismatched ``row_hash`` or a broken ``prev_hash`` link).
    """
    rows = (
        await session.scalars(
            select(AuditLog).order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
    ).all()
    expected_prev = GENESIS
    for index, row in enumerate(rows):
        if (row.prev_hash or GENESIS) != expected_prev:
            return False, index
        if _recompute(row, expected_prev) != row.row_hash:
            return False, index
        expected_prev = row.row_hash
    return True, None
