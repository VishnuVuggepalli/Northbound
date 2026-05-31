"""Devices router — onboarding wizard backend + CRUD.

Onboarding flow (principal-engineering D7):
* ``test-connection`` / ``discover`` are stateless probes — NO DB writes.
* ``POST /api/devices`` is the atomic confirm: device + ports + baseline
  backup + audit entry in a single transaction (rollback on any failure).

Credentials are encrypted at rest via :class:`CredVault`, used transiently
for probes, and NEVER returned in any response or written to a log.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.deps import get_current_user, require_admin
from northbound.db import get_session
from northbound.drivers.base import AuthError, DriverError, ReachabilityError
from northbound.drivers.factory import driver_for, driver_from_params
from northbound.drivers.registry import get_driver_class
from northbound.models.device import Device
from northbound.models.enums import Environment
from northbound.models.user import User
from northbound.schemas.device import (
    ConnectionTestIn,
    CredentialsRotateIn,
    DeviceCreateIn,
    DeviceOut,
    DiscoverIn,
    DiscoverOut,
    PortOut,
    TestConnectionOut,
)
from northbound.schemas.driver import (
    ConnectionParams,
    Credentials,
    DiscoveryResult,
    PortState,
)
from northbound.services import audit, reachability
from northbound.services.credvault import FernetCredVault, serialize_credentials
from northbound.services.device_policy import is_writable
from northbound.services.onboarding import onboard_device

logger = logging.getLogger("northbound.api.devices")

router = APIRouter(prefix="/api/devices", tags=["devices"])


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _conn_params(mgmt_ip: str, port: int | None, prefer_native_api: bool) -> ConnectionParams:
    return ConnectionParams(host=mgmt_ip, port=port, prefer_native_api=prefer_native_api)


def _require_known_platform(platform_id: str) -> None:
    try:
        get_driver_class(platform_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown platform_id: {platform_id}",
        ) from exc


def _port_out(port: PortState) -> PortOut:
    return PortOut(
        name=port.name,
        admin_up=port.admin_up,
        link_up=port.link_up,
        speed_mbps=port.speed_mbps,
        duplex=port.duplex,
        mac=port.mac,
        mtu=port.mtu,
        untagged_vlan=port.untagged_vlan,
        tagged_vlans=list(port.tagged_vlans),
        description=port.description,
        host_model=port.host_model,
        bmc_ip=port.bmc_ip,
        notes=port.notes,
    )


def _device_out(device: Device, *, reachable: bool | None = None) -> DeviceOut:
    """Project a device row to its public DTO, attaching capability info.

    Credentials are never read here — only declared capabilities + policy.
    """
    capabilities = None
    try:
        capabilities = get_driver_class(device.platform).capabilities
    except KeyError:
        capabilities = None
    return DeviceOut(
        id=device.id,
        name=device.name,
        environment=device.environment,
        role=device.role,
        platform=device.platform,
        mgmt_ip=device.mgmt_ip,
        ssh_user=device.ssh_user,
        prefer_native_api=device.prefer_native_api,
        capabilities=capabilities,
        writable=is_writable(device),
        reachable=reachable,
    )


async def _load_device(session: AsyncSession, device_id: str) -> Device:
    device = await session.scalar(select(Device).where(Device.id == device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


# --------------------------------------------------------------------------- #
# onboarding probes (stateless — never persist)
# --------------------------------------------------------------------------- #
@router.post("/test-connection", response_model=TestConnectionOut)
async def test_connection(
    body: ConnectionTestIn,
    _admin: Annotated[User, Depends(require_admin)],
) -> TestConnectionOut:
    """Live credential probe. Does NOT persist anything."""
    _require_known_platform(body.platform_id)
    driver = driver_from_params(
        body.platform_id,
        _conn_params(body.mgmt_ip, body.port, body.prefer_native_api),
        body.credentials.to_credentials(),
    )
    try:
        result = await driver.test_credentials()
    except (AuthError, ReachabilityError) as exc:
        return TestConnectionOut(ok=False, latency_ms=0.0, platform_version=None, error=str(exc))
    finally:
        await driver.aclose()
    return TestConnectionOut(
        ok=result.ok,
        latency_ms=result.latency_ms,
        platform_version=result.platform_version,
        error=result.error,
    )


@router.post("/discover", response_model=DiscoverOut)
async def discover(
    body: DiscoverIn,
    _admin: Annotated[User, Depends(require_admin)],
) -> DiscoverOut:
    """Discovery preview for the wizard. Does NOT persist anything."""
    _require_known_platform(body.platform_id)
    driver = driver_from_params(
        body.platform_id,
        _conn_params(body.mgmt_ip, body.port, body.prefer_native_api),
        body.credentials.to_credentials(),
    )
    try:
        result = await driver.discover()
    except (AuthError, ReachabilityError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discovery failed: {exc}",
        ) from exc
    finally:
        await driver.aclose()
    return DiscoverOut(
        hostname=result.hostname,
        ports=[_port_out(p) for p in result.ports],
        running_config=result.running_config,
        services=dict(result.services),
    )


# --------------------------------------------------------------------------- #
# atomic onboard (the only write that creates a device)
# --------------------------------------------------------------------------- #
@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def create_device(
    body: DeviceCreateIn,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceOut:
    """Atomic onboard: re-discover, then persist device + ports + backup + audit.

    Discovery runs BEFORE the transaction — if it fails, there is no DB hit.
    The persist runs inside one ``session.begin()`` block; any failure rolls
    the whole unit back, leaving no orphan device or ports.
    """
    _require_known_platform(body.platform_id)
    creds: Credentials = body.credentials.to_credentials()

    # Step 6: re-run discovery (outside the transaction). No DB hit on failure.
    driver = driver_from_params(
        body.platform_id,
        _conn_params(body.mgmt_ip, body.port, body.prefer_native_api),
        creds,
    )
    try:
        discovery: DiscoveryResult = await driver.discover()
    except (AuthError, ReachabilityError, DriverError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Discovery failed; device not onboarded: {exc}",
        ) from exc
    finally:
        await driver.aclose()

    vault = FernetCredVault.from_settings()

    # Step 7: one atomic unit via a SAVEPOINT. begin_nested() releases the
    # savepoint on success and rolls it back on any raise, leaving no orphan
    # device/ports. The surrounding request transaction (get_session) commits
    # on success / rolls back on a propagated error — so a 409 below leaves a
    # clean session with nothing half-written.
    try:
        async with session.begin_nested():
            device = await onboard_device(
                session,
                name=body.name,
                environment=body.environment,
                role=body.role,
                platform_id=body.platform_id,
                mgmt_ip=body.mgmt_ip,
                ssh_user=body.ssh_user,
                prefer_native_api=body.prefer_native_api,
                creds=creds,
                discovery=discovery,
                vault=vault,
                actor_user_id=admin.id,
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device name already exists",
        ) from exc

    return _device_out(device)


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[DeviceOut])
async def list_devices(
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    environment: Environment | None = None,
) -> list[DeviceOut]:
    """List devices (optional ``?environment=`` filter). Never returns creds."""
    stmt = select(Device).order_by(Device.name)
    if environment is not None:
        stmt = stmt.where(Device.environment == environment)
    rows = await session.scalars(stmt)
    # Reachability is served from the in-mem poll map (None = not yet polled).
    return [_device_out(d, reachable=reachability.is_reachable(d.id)) for d in rows.all()]


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceOut:
    """Device detail. Never returns creds."""
    device = await _load_device(session, device_id)
    return _device_out(device, reachable=reachability.is_reachable(device.id))


# --------------------------------------------------------------------------- #
# rotate credentials (re-test first; old creds retained on failure)
# --------------------------------------------------------------------------- #
@router.patch("/{device_id}/credentials", response_model=DeviceOut)
async def rotate_credentials(
    device_id: str,
    body: CredentialsRotateIn,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceOut:
    """Re-test new creds against the device; only store them if the probe passes.

    On a failed probe the stored (old) credentials are left untouched — 400.
    """
    device = await _load_device(session, device_id)
    new_creds = body.credentials.to_credentials()

    driver = driver_for(device, new_creds)
    try:
        result = await driver.test_credentials()
    except (AuthError, ReachabilityError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"New credentials rejected; not rotated: {exc}",
        ) from exc
    finally:
        await driver.aclose()
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"New credentials failed test; not rotated: {result.error or 'probe failed'}",
        )

    vault = FernetCredVault.from_settings()
    device.encrypted_credentials = serialize_credentials(new_creds, vault)
    session.add(device)
    await session.flush()
    return _device_out(device)


# --------------------------------------------------------------------------- #
# offboard (port_metadata + backups cascade via FK ondelete=CASCADE; a device
# with change-request history is blocked from hard-delete by FK RESTRICT so the
# compliance trail is retained — surfaced as 409)
# --------------------------------------------------------------------------- #
@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Offboard a device.

    port_metadata + backups cascade via FK ondelete=CASCADE (operational data).
    Change-request history uses FK ondelete=RESTRICT, so a device that has any
    change requests CANNOT be hard-deleted — the compliance trail must be
    retained. That case surfaces as 409 Conflict rather than an unhandled 500.
    """
    device = await _load_device(session, device_id)
    name = device.name
    platform = device.platform
    mgmt_ip = device.mgmt_ip
    await session.delete(device)
    try:
        # Force the DELETE now so the FK RESTRICT fires here (not at commit),
        # letting us attribute the IntegrityError to the retained change trail.
        await session.flush()
    except IntegrityError as exc:
        # INVARIANT: rollback() leaves the session clean; `raise` MUST follow
        # immediately. Do not add session work between here and the raise —
        # any add()/flush() after rollback would open a fresh implicit
        # transaction on a session the caller expects to be aborted.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "device has change-request history and cannot be hard-deleted; "
                "the change trail must be retained"
            ),
        ) from exc

    # Chain the offboard audit row through append_audit so it gets a real
    # row_hash and links to the current tip (was previously written with an
    # empty row_hash, which broke verify_chain and re-rooted the next append).
    # target_device_id stays None because the device row is being deleted.
    await audit.append_audit(
        session,
        user_id=admin.id,
        action="device.offboarded",
        target_device_id=None,
        before={"name": name, "platform": platform, "mgmt_ip": mgmt_ip},
        after=None,
        result="ok",
    )
