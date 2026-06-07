"""In-process reachability map (principal-engineering D2).

Reachability is *device* truth, cached in-memory and refreshed by the
``poll_reachability`` background job every ``poll_interval_seconds`` (default
60s — matching the D2 reachability TTL). The map is a module-level dict keyed
by ``device_id``; the API layer (``/api/devices``) reads it to populate
``DeviceOut.reachable``.

Single-worker invariant (D2/D9): one process means one authoritative map, so
no cross-worker fragmentation. The swap point for a multi-worker future is
:data:`_MAP` (→ Redis); the read/write helpers below keep their signatures.

Values are immutable :class:`ReachabilityStatus` snapshots — callers never
mutate an entry in place (coding-style: immutability). A missing entry means
"not yet polled" and is reported as ``reachable=None`` to the API.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class ReachabilityStatus:
    """A point-in-time reachability snapshot for one device."""

    reachable: bool
    checked_at: dt.datetime


# Module-level map: device_id -> ReachabilityStatus. SWAP POINT for Redis at
# multi-worker scale (see module docstring).
_MAP: dict[str, ReachabilityStatus] = {}


def record(device_id: str, *, reachable: bool, checked_at: dt.datetime) -> bool:
    """Store (replace) the reachability snapshot for a device.

    Returns ``True`` when the ``reachable`` value transitioned (including the
    first-ever observation), so a caller can publish a live-state event only on
    change rather than on every poll tick.
    """
    previous = _MAP.get(device_id)
    _MAP[device_id] = ReachabilityStatus(reachable=reachable, checked_at=checked_at)
    return previous is None or previous.reachable != reachable


def get(device_id: str) -> ReachabilityStatus | None:
    """Latest snapshot for a device, or ``None`` if never polled."""
    return _MAP.get(device_id)


def is_reachable(device_id: str) -> bool | None:
    """Convenience: just the boolean, or ``None`` if never polled.

    ``None`` is meaningful — the API renders it as "unknown" rather than
    asserting a device is down before the first poll has run.
    """
    status = _MAP.get(device_id)
    return status.reachable if status is not None else None


def snapshot() -> dict[str, ReachabilityStatus]:
    """Defensive copy of the whole map (for diagnostics / bulk reads)."""
    return dict(_MAP)


def clear() -> None:
    """Test-only: wipe the map so state never leaks across cases."""
    _MAP.clear()
