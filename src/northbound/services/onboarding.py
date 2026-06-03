"""Atomic device onboarding — the transactional confirm step.

The wizard's steps 1-6 are stateless probes (test-connection, discover).
Step 7 (this module) is one DB transaction:

1. (caller re-runs discover, then) INSERT device with encrypted credentials
2. INSERT port_metadata x N (parsed host_model / bmc_ip from descriptions)
3. INSERT config_backup (initial baseline)
4. INSERT audit_log (``device.onboarded``)

Any failure rolls the whole thing back — no half-onboarded device, no orphan
ports. The caller owns the session and the surrounding ``begin()`` block so
the transaction boundary is explicit and testable.
"""

from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.enums import DeviceRole
from northbound.models.port_metadata import PortMetadata
from northbound.schemas.driver import Credentials, DiscoveryResult
from northbound.services import audit
from northbound.services.credvault import CredVault, serialize_credentials

# Legacy port-description convention (see plan.md):
#   "VLAN-<untagged> | <host_model> | <bmc_ip>"
# Fields are pipe-separated; the VLAN segment is optional/ignored here (live
# VLAN comes from the device). We extract host_model + bmc_ip when present.
_PIPE = "|"
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def parse_description(description: str) -> tuple[str, str]:
    """Parse ``host_model`` and ``bmc_ip`` from a legacy port description.

    Returns ``("", "")`` when the description doesn't follow the convention.
    Tolerant of missing segments and surrounding whitespace.
    """
    if _PIPE not in description:
        return "", ""
    segments = [seg.strip() for seg in description.split(_PIPE)]
    # Drop a leading "VLAN-<n>" segment if present; it's live state, not metadata.
    if segments and segments[0].upper().startswith("VLAN-"):
        segments = segments[1:]
    host_model = segments[0] if len(segments) >= 1 else ""
    bmc_candidate = segments[1] if len(segments) >= 2 else ""
    bmc_ip = bmc_candidate if _IPV4_RE.match(bmc_candidate) else ""
    return host_model, bmc_ip


async def onboard_device(
    session: AsyncSession,
    *,
    name: str,
    environment: str,
    role: DeviceRole,
    platform_id: str,
    mgmt_ip: str,
    ssh_user: str | None,
    prefer_native_api: bool,
    creds: Credentials,
    discovery: DiscoveryResult,
    vault: CredVault,
    actor_user_id: str | None,
) -> Device:
    """Persist a device + ports + baseline backup + audit entry in one unit.

    The caller is responsible for the transaction boundary (``session.begin``)
    and for committing. This function only adds + flushes so the device id is
    available for the dependent rows; it never commits or rolls back itself.
    """
    now = dt.datetime.now(tz=dt.UTC)

    device = Device(
        name=name,
        environment=environment,
        platform=platform_id,
        role=role,
        mgmt_ip=mgmt_ip,
        ssh_user=ssh_user,
        prefer_native_api=prefer_native_api,
        encrypted_credentials=serialize_credentials(creds, vault),
    )
    session.add(device)
    # Flush to surface a duplicate-name IntegrityError early and to get device.id.
    await session.flush()

    for port in discovery.ports:
        host_model, bmc_ip = parse_description(port.description)
        # A driver may already populate host_model/bmc_ip directly; prefer those.
        session.add(
            PortMetadata(
                device_id=device.id,
                port_name=port.name,
                host_model=port.host_model or host_model,
                bmc_ip=port.bmc_ip or bmc_ip,
                notes=port.notes,
            )
        )

    session.add(
        ConfigBackup(
            device_id=device.id,
            config_text=discovery.running_config,
            fetched_at=now,
            fetched_by=actor_user_id or "system",
        )
    )

    # Chain the audit row through append_audit so it gets a real row_hash and
    # links to the current chain tip. This runs inside the caller's
    # savepoint/transaction (create_device wraps it in begin_nested), so the
    # device + ports + backup + audit row commit or roll back atomically.
    await audit.append_audit(
        session,
        user_id=actor_user_id,
        action="device.onboarded",
        target_device_id=device.id,
        before=None,
        after={"name": name, "platform": platform_id, "mgmt_ip": mgmt_ip},
        result="ok",
    )
    await session.flush()
    return device


async def rediscover_device(
    session: AsyncSession,
    *,
    device: Device,
    discovery: DiscoveryResult,
    actor_user_id: str | None,
) -> tuple[int, int]:
    """Re-run discovery's persistence for an already-onboarded device.

    NON-DESTRUCTIVE: existing ``PortMetadata`` rows are left untouched (human edits
    — notes/bmc_ip overrides — are preserved). Only ports seen for the FIRST time
    get a fresh metadata row (description re-parsed), and a new baseline
    ``ConfigBackup`` is written. The caller owns the transaction.

    Returns ``(ports_total, ports_added)``.
    """
    now = dt.datetime.now(tz=dt.UTC)
    existing = set(
        await session.scalars(
            select(PortMetadata.port_name).where(PortMetadata.device_id == device.id)
        )
    )
    added = 0
    for port in discovery.ports:
        if port.name in existing:
            continue
        host_model, bmc_ip = parse_description(port.description)
        session.add(
            PortMetadata(
                device_id=device.id,
                port_name=port.name,
                host_model=port.host_model or host_model,
                bmc_ip=port.bmc_ip or bmc_ip,
                notes=port.notes,
            )
        )
        added += 1

    session.add(
        ConfigBackup(
            device_id=device.id,
            config_text=discovery.running_config,
            fetched_at=now,
            fetched_by=actor_user_id or "system",
        )
    )
    await audit.append_audit(
        session,
        user_id=actor_user_id,
        action="device.rediscovered",
        target_device_id=device.id,
        after={"ports_total": len(discovery.ports), "ports_added": added},
        result="ok",
    )
    await session.flush()
    return len(discovery.ports), added
