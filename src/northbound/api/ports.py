"""Ports + config router (``/api/devices/{id}/...``).

* ``GET  /ports`` / ``GET /ports/{name}`` — live port state (cached 30s) +
  metadata, any authenticated user.
* ``PATCH /ports/{name}`` — admin direct edit of port *metadata* (DB only; no
  device write, so ``assert_writable`` is intentionally NOT called here — the
  read-only guard protects device config, and metadata is local annotation).
* config read / backup-now / backup list / backup diff.
"""

from __future__ import annotations

import datetime as dt
import difflib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound._lib.cache import CacheMiss, TTLCache
from northbound.api.deps import get_current_user, require_admin
from northbound.api.limiter import limiter, write_rate_key, write_rate_limit_provider
from northbound.config import get_settings
from northbound.db import get_session
from northbound.drivers.base import DriverError
from northbound.drivers.factory import driver_for
from northbound.models.audit_log import AuditLog
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.port_metadata import PortMetadata
from northbound.models.user import User
from northbound.schemas.audit import audit_entry_out
from northbound.schemas.driver import Credentials, PortChange
from northbound.schemas.port import (
    BackupDiffOut,
    BackupOut,
    ConfigOut,
    DeviceFactsOut,
    L3InterfaceOut,
    MacEntryOut,
    MgmtServiceOut,
    OspfInterfaceOut,
    PortConfigIn,
    PortDescriptionIn,
    PortDetailOut,
    PortMetadataPatchIn,
    PortStateOut,
    ProtocolDetailOut,
    ProtocolStatusOut,
    ProtocolTableOut,
    SystemInfoOut,
    VlanInfoOut,
)
from northbound.services import audit, port_state
from northbound.services.credvault import FernetCredVault, deserialize_credentials
from northbound.services.device_policy import assert_writable

router = APIRouter(prefix="/api/devices", tags=["ports"])

# Per-device running-config cache (separate concern from port_state; D2 lists
# running config as a 30s in-mem per-device cache). TTL-bound + capacity-bound:
# a plain dict would grow with the device count and serve arbitrarily stale
# configs as cached=True forever. SWAP POINT for Redis at multi-worker scale,
# same as port_state._cache.
_config_cache: TTLCache[str] = TTLCache(
    capacity=get_settings().port_state_cache_capacity,
    default_ttl=get_settings().port_state_ttl_seconds,
)


def invalidate_device_caches(device_id: str) -> None:
    """Drop all cached live state for a device (running config + port view).

    Called on writes and on device offboarding so no stale entry outlives the
    device or a config change."""
    _config_cache.delete(device_id)
    port_state.invalidate(device_id)


async def _load_device(session: AsyncSession, device_id: str) -> Device:
    device = await session.scalar(select(Device).where(Device.id == device_id))
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


def _credentials_for(device: Device) -> Credentials:
    if device.encrypted_credentials is None:
        return Credentials()
    vault = FernetCredVault.from_settings()
    return deserialize_credentials(device.encrypted_credentials, vault)


# --------------------------------------------------------------------------- #
# ports
# --------------------------------------------------------------------------- #
@router.get("/{device_id}/ports", response_model=list[PortStateOut])
async def get_ports(
    device_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh: bool = False,
) -> list[PortStateOut]:
    """Live port list (cached 30s). ``?refresh=true`` bypasses the cache."""
    device = await _load_device(session, device_id)
    try:
        views = await port_state.get_ports(session, device, refresh=refresh)
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Port fetch failed: {exc}"
        ) from exc
    return [PortStateOut.from_view(v) for v in views]


@router.get("/{device_id}/ports/{port_name:path}", response_model=PortDetailOut)
async def get_port_detail(
    device_id: str,
    port_name: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh: bool = False,
) -> PortDetailOut:
    """Single-port detail: live state + metadata + recent audit history."""
    device = await _load_device(session, device_id)
    try:
        views = await port_state.get_ports(session, device, refresh=refresh)
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Port fetch failed: {exc}"
        ) from exc
    match = next((v for v in views if v.live.name == port_name), None)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Port not found")

    history_rows = await session.scalars(
        select(AuditLog)
        .where(AuditLog.target_device_id == device_id, AuditLog.target_port == port_name)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(20)
    )
    return PortDetailOut(
        port=PortStateOut.from_view(match),
        history=[audit_entry_out(r) for r in history_rows.all()],
    )


async def _apply_direct_port_change(
    session: AsyncSession,
    device: Device,
    port_name: str,
    change: PortChange,
    *,
    admin: User,
    action: str,
    after: dict[str, object],
) -> None:
    """Admin DIRECT device write: backup → render → apply → confirm + audit.

    Shared by the description and config endpoints. Immediate commit (no approval
    gate); raises 502 on driver/apply failure and always closes the driver.
    """
    assert_writable(device)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        backup_text = await driver.backup_config()
        session.add(
            ConfigBackup(
                device_id=device.id,
                config_text=backup_text,
                fetched_at=dt.datetime.now(tz=dt.UTC),
                fetched_by=admin.id,
            )
        )
        await session.flush()
        diff = await driver.render_change(port_name, change)
        result = await driver.apply_change(
            diff, confirm_seconds=get_settings().commit_confirm_seconds
        )
        if not result.success:
            raise DriverError(f"Apply failed: {result.error}")
        if result.confirm_token:
            await driver.confirm(result.confirm_token)  # make permanent (direct write)
    except DriverError as exc:
        # The 502 propagates through get_session → rollback(), which would
        # silently discard BOTH the backup row and any record of the attempt
        # (worst case: apply succeeded, confirm failed → device touched, zero
        # trace). Persist the failure audit + backup with an explicit commit
        # before raising — same terminal-error commit boundary change_apply uses.
        await audit.append_audit(
            session,
            user_id=admin.id,
            action=action,
            target_device_id=device.id,
            target_port=port_name,
            after={**after, "error": str(exc)},
            result="error",
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Write failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()

    await audit.append_audit(
        session,
        user_id=admin.id,
        action=action,
        target_device_id=device.id,
        target_port=port_name,
        after=after,
        result="ok",
    )
    invalidate_device_caches(device.id)  # running config + live port view changed


@router.patch("/{device_id}/ports/{port_name:path}/description")
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def set_port_description(
    request: Request,
    device_id: str,
    port_name: str,
    body: PortDescriptionIn,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Admin-only DIRECT write of the on-device port description.

    Declared BEFORE the metadata ``:path`` route so ``…/description`` matches
    here, not as a port named ``…/description``.
    """
    device = await _load_device(session, device_id)
    await _apply_direct_port_change(
        session,
        device,
        port_name,
        PortChange(description=body.description),
        admin=admin,
        action="port.description_set",
        after={"description": body.description},
    )
    return {"port_name": port_name, "description": body.description}


@router.patch("/{device_id}/ports/{port_name:path}/config")
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def set_port_config(
    request: Request,
    device_id: str,
    port_name: str,
    body: PortConfigIn,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Admin-only DIRECT write of device port tunables.

    Covers port-mode (access/trunk), native/untagged VLAN, tagged VLANs, MTU and
    admin enable/disable. Declared BEFORE the metadata ``:path`` route. Immediate
    commit, no approval gate; 403 for non-admin, 422 if no field is set.
    """
    device = await _load_device(session, device_id)
    change = PortChange(
        port_mode=body.port_mode,
        untagged_vlan=body.untagged_vlan,
        tagged_vlans=body.tagged_vlans,
        mtu=body.mtu,
        enabled=body.enabled,
    )
    after = body.model_dump(exclude_none=True)
    await _apply_direct_port_change(
        session,
        device,
        port_name,
        change,
        admin=admin,
        action="port.config_set",
        after=after,
    )
    return {"port_name": port_name, **after}


@router.patch("/{device_id}/ports/{port_name:path}", response_model=PortStateOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def patch_port_metadata(
    request: Request,
    device_id: str,
    port_name: str,
    body: PortMetadataPatchIn,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PortStateOut:
    """Admin direct edit of port *metadata* (host_model/bmc_ip/notes).

    Metadata-only: this writes the DB ``port_metadata`` row, NOT the device, so
    ``assert_writable`` is deliberately not invoked. Writes an audit entry and
    stamps ``last_human_edit_*``.
    """
    device = await _load_device(session, device_id)

    meta = await session.scalar(
        select(PortMetadata).where(
            PortMetadata.device_id == device_id, PortMetadata.port_name == port_name
        )
    )
    if meta is None:
        meta = PortMetadata(device_id=device_id, port_name=port_name)
        session.add(meta)

    before = {"host_model": meta.host_model, "bmc_ip": meta.bmc_ip, "notes": meta.notes}
    if body.host_model is not None:
        meta.host_model = body.host_model
    if body.bmc_ip is not None:
        meta.bmc_ip = body.bmc_ip
    if body.notes is not None:
        meta.notes = body.notes
    meta.last_human_edit_at = dt.datetime.now(tz=dt.UTC)
    meta.last_human_edit_by = admin.id
    await session.flush()

    await audit.append_audit(
        session,
        user_id=admin.id,
        action="port.metadata_edited",
        target_device_id=device_id,
        target_port=port_name,
        before=before,
        after={"host_model": meta.host_model, "bmc_ip": meta.bmc_ip, "notes": meta.notes},
        result="ok",
    )

    views = await port_state.get_ports(session, device, refresh=False)
    match = next((v for v in views if v.live.name == port_name), None)
    if match is None:
        # Metadata exists but the live port is absent — surface metadata alone.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Port not present on device (metadata saved)",
        )
    return PortStateOut.from_view(match)


# --------------------------------------------------------------------------- #
# config + backups
# --------------------------------------------------------------------------- #
@router.get("/{device_id}/config", response_model=ConfigOut)
async def get_config(
    device_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    refresh: bool = False,
) -> ConfigOut:
    """Running config (cached). ``?refresh=true`` re-fetches from the device."""
    device = await _load_device(session, device_id)
    if not refresh:
        cached = _config_cache.get(device_id)
        if not isinstance(cached, CacheMiss):
            return ConfigOut(config_text=cached, cached=True)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        text = await driver.get_running_config()
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Config fetch failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()
    _config_cache.set(device_id, text)
    return ConfigOut(config_text=text, cached=False)


@router.get("/{device_id}/system", response_model=SystemInfoOut)
async def get_system_info(
    device_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SystemInfoOut:
    """Live system snapshot: control-plane protocols, mgmt services, MAC table.

    Sections a driver can't reach come back empty (``mac_supported=false``
    distinguishes an unreadable MAC table from a genuinely empty one).
    """
    device = await _load_device(session, device_id)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        info = await driver.get_system_info()
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"System info fetch failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()
    return SystemInfoOut(
        facts=DeviceFactsOut(
            model=info.facts.model,
            os_version=info.facts.os_version,
            serial=info.facts.serial,
            uptime=info.facts.uptime,
            license=info.facts.license,
            base_mac=info.facts.base_mac,
            released=info.facts.released,
        ),
        protocols=[
            ProtocolStatusOut(
                name=p.name,
                enabled=p.enabled,
                detail=p.detail,
                params=list(p.params),
                has_detail=p.has_detail,
            )
            for p in info.protocols
        ],
        services=[
            MgmtServiceOut(
                name=s.name,
                enabled=s.enabled,
                port=s.port,
                detail=s.detail,
                configured=s.configured,
            )
            for s in info.services
        ],
        mac_table=[
            MacEntryOut(vlan=m.vlan, mac=m.mac, interface=m.interface, type=m.type, age=m.age)
            for m in info.mac_table
        ],
        mac_supported=info.mac_supported,
    )


@router.get("/{device_id}/protocols/{slug}", response_model=ProtocolDetailOut)
async def get_protocol_detail(
    device_id: str,
    slug: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProtocolDetailOut:
    """Operational detail (named tables) for one protocol — e.g. OSPF neighbors
    + link-state database. Parsed from device CLI gets via TextFSM."""
    device = await _load_device(session, device_id)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        detail = await driver.get_protocol_detail(slug)
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Protocol detail failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()
    return ProtocolDetailOut(
        slug=detail.slug,
        tables=[
            ProtocolTableOut(title=t.title, columns=list(t.columns), rows=[list(r) for r in t.rows])
            for t in detail.tables
        ],
        error=detail.error,
    )


@router.get("/{device_id}/vlans", response_model=list[VlanInfoOut])
async def get_vlans(
    device_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VlanInfoOut]:
    """The device's VLAN database: id, name, description, L3 SVI, member-port
    count. Backs the VLANs view and the request VLAN picker."""
    device = await _load_device(session, device_id)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        vlans = await driver.get_vlans()
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"VLAN fetch failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()
    return [
        VlanInfoOut(
            vlan_id=v.vlan_id,
            name=v.name,
            description=v.description,
            l3_interface=v.l3_interface,
            port_count=v.port_count,
        )
        for v in vlans
    ]


@router.get("/{device_id}/l3-interfaces", response_model=list[L3InterfaceOut])
async def get_l3_interfaces(
    device_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[L3InterfaceOut]:
    """Addressed/non-switchport interfaces: management port, L3 VLAN SVIs, LAGs."""
    device = await _load_device(session, device_id)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        ifaces = await driver.get_l3_interfaces()
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Interface fetch failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()
    return [
        L3InterfaceOut(
            name=i.name,
            kind=i.kind,
            ipv4=i.ipv4,
            gateway=i.gateway,
            mtu=i.mtu,
            enabled=i.enabled,
            detail=i.detail,
        )
        for i in ifaces
    ]


@router.get("/{device_id}/ospf-interfaces", response_model=list[OspfInterfaceOut])
async def get_ospf_interfaces(
    device_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[OspfInterfaceOut]:
    """OSPF-enabled interfaces (name/area/tuning) from the device config."""
    device = await _load_device(session, device_id)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        ifaces = await driver.get_ospf_interfaces()
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OSPF fetch failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()
    return [
        OspfInterfaceOut(
            name=i.name,
            area=i.area,
            cost=i.cost,
            hello_interval=i.hello_interval,
            dead_interval=i.dead_interval,
            passive=i.passive,
        )
        for i in ifaces
    ]


@router.post(
    "/{device_id}/config/backup",
    response_model=BackupOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def backup_now(
    request: Request,
    device_id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BackupOut:
    """Take a config backup now (admin)."""
    device = await _load_device(session, device_id)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        text = await driver.backup_config()
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Backup failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()
    now = dt.datetime.now(tz=dt.UTC)
    backup = ConfigBackup(
        device_id=device_id, config_text=text, fetched_at=now, fetched_by=admin.id
    )
    session.add(backup)
    await session.flush()
    await audit.append_audit(
        session,
        user_id=admin.id,
        action="config.backed_up",
        target_device_id=device_id,
        result="ok",
    )
    return BackupOut(
        id=backup.id,
        device_id=device_id,
        fetched_at=now.isoformat(),
        fetched_by=admin.id,
    )


@router.get("/{device_id}/config/backups", response_model=list[BackupOut])
async def list_backups(
    device_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BackupOut]:
    """List a device's config backups, newest first."""
    await _load_device(session, device_id)
    rows = await session.scalars(
        select(ConfigBackup)
        .where(ConfigBackup.device_id == device_id)
        .order_by(ConfigBackup.fetched_at.desc())
    )
    return [
        BackupOut(
            id=b.id,
            device_id=b.device_id,
            fetched_at=b.fetched_at.isoformat(),
            fetched_by=b.fetched_by,
        )
        for b in rows.all()
    ]


@router.get("/{device_id}/config/backups/{backup_id}/diff", response_model=BackupDiffOut)
async def backup_diff(
    device_id: str,
    backup_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BackupDiffOut:
    """Unified diff of a stored backup vs the current running config."""
    device = await _load_device(session, device_id)
    backup = await session.scalar(
        select(ConfigBackup).where(
            ConfigBackup.id == backup_id, ConfigBackup.device_id == device_id
        )
    )
    if backup is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")

    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        current = await driver.get_running_config()
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Config fetch failed: {exc}"
        ) from exc
    finally:
        await driver.aclose()

    diff = "\n".join(
        difflib.unified_diff(
            backup.config_text.splitlines(),
            current.splitlines(),
            fromfile=f"backup/{backup_id}",
            tofile="current",
            lineterm="",
        )
    )
    return BackupDiffOut(backup_id=backup_id, diff=diff)
