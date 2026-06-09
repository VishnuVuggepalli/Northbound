"""Live port-state service — cache + driver fetch + metadata merge.

Truth model (principal-engineering D2): live port state lives on the *device*;
we cache it in-process for ``port_state_ttl_seconds`` (default 30s) keyed by
device id. Port *metadata* (host_model, bmc_ip, notes) lives in the DB and is
merged onto each live port to produce a :class:`PortStateView`.

Single-worker invariant (D2/D9): the cache is a module-level in-mem dict, so
cache fragmentation is impossible while Northbound runs one worker. When it
scales to N workers this dict must become a shared store (Redis); the swap
point is :data:`_cache` here and the underlying ``TTLCache`` — the function
signatures below stay identical so callers are unaffected.

``device_state_fingerprint`` is a stable sha256 over (port_name, untagged_vlan,
sorted tagged_vlans) used for state-drift detection (capture at request file
time, re-check at apply time).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound._lib.cache import CacheMiss, TTLCache
from northbound.config import get_settings
from northbound.drivers.factory import driver_for
from northbound.models.device import Device
from northbound.models.port_metadata import PortMetadata
from northbound.schemas.driver import Credentials, PortState
from northbound.services import events
from northbound.services.credvault import FernetCredVault, deserialize_credentials


@dataclass(frozen=True)
class PortStateView:
    """Live port state with human-authored metadata layered on.

    ``live`` is the immutable driver-sourced state; ``host_model`` / ``bmc_ip``
    / ``notes`` come from the ``port_metadata`` DB row (fall back to the live
    fields, then empty). ``last_human_edit_*`` flags operator-intent drift.
    """

    live: PortState
    host_model: str
    bmc_ip: str
    notes: str
    last_human_edit_at: str | None
    last_human_edit_by: str | None


# Module-level cache: device_id -> tuple[PortState, ...]. SWAP POINT for Redis
# at multi-worker scale (see module docstring). Capacity/TTL come from settings.
_settings = get_settings()
_cache: TTLCache[tuple[PortState, ...]] = TTLCache(
    capacity=_settings.port_state_cache_capacity,
    default_ttl=_settings.port_state_ttl_seconds,
)


def _credentials_for(device: Device) -> Credentials:
    """Decrypt the device's stored credentials, or an empty bag if none."""
    if device.encrypted_credentials is None:
        return Credentials()
    vault = FernetCredVault.from_settings()
    return deserialize_credentials(device.encrypted_credentials, vault)


async def _fetch_live(device: Device) -> tuple[PortState, ...]:
    """Pull live port state from the device driver."""
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        ports = await driver.get_ports()
    finally:
        await driver.aclose()
    return tuple(ports)


def invalidate(device_id: str) -> None:
    """Drop the cached entry for a device (call after a successful apply).

    Also publishes a ``device.ports`` live-state event so any connected SSE
    client refetches the device's ports — a write just changed them.
    """
    _cache.delete(device_id)
    events.hub.publish(events.Event("device.ports", {"device_id": device_id}))


async def _cached_ports(
    device: Device,
    *,
    refresh: bool,
) -> tuple[PortState, ...]:
    """Return cached ports if fresh, else fetch live and refresh the cache.

    TTL freshness is enforced by :class:`TTLCache`; ``refresh=True`` bypasses
    the cache entirely (UI "refetch").
    """
    if not refresh:
        cached = _cache.get(device.id)
        if not isinstance(cached, CacheMiss):
            return cached
    live = await _fetch_live(device)
    _cache.set(device.id, live)
    return live


async def _metadata_map(
    session: AsyncSession,
    device_id: str,
) -> dict[str, PortMetadata]:
    """Load port_metadata rows for a device, keyed by port_name."""
    rows = await session.scalars(select(PortMetadata).where(PortMetadata.device_id == device_id))
    return {row.port_name: row for row in rows.all()}


def _merge(port: PortState, meta: PortMetadata | None) -> PortStateView:
    """Layer a metadata row onto a live port (DB metadata wins for human fields)."""
    host_model = (meta.host_model if meta else "") or port.host_model
    bmc_ip = (meta.bmc_ip if meta else "") or port.bmc_ip
    notes = (meta.notes if meta else "") or port.notes
    edit_at = meta.last_human_edit_at.isoformat() if meta and meta.last_human_edit_at else None
    edit_by = meta.last_human_edit_by if meta else None
    return PortStateView(
        live=port,
        host_model=host_model,
        bmc_ip=bmc_ip,
        notes=notes,
        last_human_edit_at=edit_at,
        last_human_edit_by=edit_by,
    )


async def get_ports(
    session: AsyncSession,
    device: Device,
    *,
    max_age_seconds: float | None = None,
    refresh: bool = False,
) -> list[PortStateView]:
    """Live port inventory for a device, merged with DB metadata.

    Fresh cache hit → served from cache; stale or ``refresh=True`` → driver
    fetch + cache refresh. ``max_age_seconds`` overrides the configured TTL for
    this call's freshness window (rarely needed; the cache TTL is the default).
    """
    # Honour a tighter freshness window: if a caller demands a stricter age
    # than the cache TTL we can't trust the cached entry, so force a refresh.
    # (Looser windows fall through to the normal TTL freshness check.)
    if max_age_seconds is not None and not refresh and max_age_seconds < _cache._default_ttl:
        refresh = True
    ports = await _cached_ports(device, refresh=refresh)
    meta = await _metadata_map(session, device.id)
    return [_merge(p, meta.get(p.name)) for p in ports]


def device_state_fingerprint(
    ports: tuple[PortState, ...] | list[PortState], port_name: str | None = None
) -> str:
    """Stable sha256 over VLAN-bearing port state, for drift detection.

    Canonical input: sorted by port name; each port reduced to
    ``[name, untagged_vlan, sorted(tagged_vlans)]``. Whitespace-free JSON keeps
    the hash reproducible across processes.

    When ``port_name`` is given the hash covers *only* that port, so drift is
    scoped to the request's own switchport — an unrelated edit elsewhere on the
    device no longer blocks the apply. ``port_name=None`` hashes the whole device
    (the right scope for device-level changes: VLAN db, SVIs, VRFs, OSPF).
    """
    selected = ports if port_name is None else [p for p in ports if p.name == port_name]
    canonical = sorted(
        ([p.name, p.untagged_vlan, sorted(p.tagged_vlans)] for p in selected),
        key=lambda row: str(row[0]),
    )
    blob = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def current_fingerprint(
    device: Device, *, refresh: bool = True, port_name: str | None = None
) -> str:
    """Fetch (optionally fresh) live ports and return their fingerprint.

    ``port_name`` scopes the hash to a single switchport (see
    :func:`device_state_fingerprint`)."""
    ports = await _cached_ports(device, refresh=refresh)
    return device_state_fingerprint(ports, port_name=port_name)
