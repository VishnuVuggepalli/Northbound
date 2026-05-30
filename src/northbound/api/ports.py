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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.deps import get_current_user, require_admin
from northbound.db import get_session
from northbound.drivers.base import DriverError
from northbound.drivers.factory import driver_for
from northbound.models.audit_log import AuditLog
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.port_metadata import PortMetadata
from northbound.models.user import User
from northbound.schemas.audit import audit_entry_out
from northbound.schemas.driver import Credentials
from northbound.schemas.port import (
    BackupDiffOut,
    BackupOut,
    ConfigOut,
    PortDetailOut,
    PortMetadataPatchIn,
    PortStateOut,
)
from northbound.services import audit, port_state
from northbound.services.credvault import FernetCredVault, deserialize_credentials

router = APIRouter(prefix="/api/devices", tags=["ports"])

# Per-device running-config cache (separate concern from port_state; D2 lists
# running config as a 30s in-mem per-device cache). SWAP POINT for Redis at
# multi-worker scale, same as port_state._cache.
_config_cache: dict[str, str] = {}


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


@router.get("/{device_id}/ports/{port_name}", response_model=PortDetailOut)
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


@router.patch("/{device_id}/ports/{port_name}", response_model=PortStateOut)
async def patch_port_metadata(
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
    if not refresh and device_id in _config_cache:
        return ConfigOut(config_text=_config_cache[device_id], cached=True)
    creds = _credentials_for(device)
    driver = driver_for(device, creds)
    try:
        text = await driver.get_running_config()
    except DriverError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Config fetch failed: {exc}"
        ) from exc
    _config_cache[device_id] = text
    return ConfigOut(config_text=text, cached=False)


@router.post(
    "/{device_id}/config/backup",
    response_model=BackupOut,
    status_code=status.HTTP_201_CREATED,
)
async def backup_now(
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
