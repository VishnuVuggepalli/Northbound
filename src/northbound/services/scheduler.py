"""In-process background jobs (APScheduler) — principal-engineering polling jobs.

One :class:`~apscheduler.schedulers.asyncio.AsyncIOScheduler` runs four jobs on
the app event loop (no Redis/Celery broker — single-process architecture, D9):

  poll_reachability   IntervalTrigger(poll_interval_seconds, default 60s)
                      Probe every device's ``driver.reachable()`` with a timeout
                      and update the in-mem reachability map. A failure marks the
                      device unreachable; it never raises out of the job.
  nightly_backup      CronTrigger(nightly_backup_cron, default 03:00)
                      ``driver.backup_config()`` per device → ConfigBackup row +
                      audit. A per-device error is logged and the batch continues.
  verify_audit_chain  CronTrigger(audit_verify_cron, default 03:30)
                      ``verify_chain`` over the audit log; a break logs CRITICAL +
                      a structured alert. No auto-repair — tamper evidence is loud.
  reconciler_tick     IntervalTrigger(reconciler_interval_seconds, default 10s)
                      Crash/deadline recovery for in-flight change requests (D3/D4).

Job discipline (hard rules):
  * Each job opens its OWN session from ``async_session_factory`` and closes it
    (never a request-scoped session).
  * A throwing job must not kill the scheduler — every job body is wrapped so
    exceptions are logged, not propagated to APScheduler's executor.

The scheduler is built here and started/stopped by the FastAPI lifespan in
``main.py`` (gated on ``settings.enable_scheduler`` so tests never spawn timers).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from northbound.config import Settings, get_settings
from northbound.db import async_session_factory
from northbound.drivers.factory import driver_for
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.schemas.driver import Credentials
from northbound.services import audit, reachability, reconciler
from northbound.services.audit import verify_chain
from northbound.services.credvault import FernetCredVault, deserialize_credentials

logger = logging.getLogger("northbound.services.scheduler")

# Stable job ids — asserted by tests and used for replace_existing safety.
JOB_POLL_REACHABILITY = "poll_reachability"
JOB_NIGHTLY_BACKUP = "nightly_backup"
JOB_VERIFY_AUDIT_CHAIN = "verify_audit_chain"
JOB_RECONCILER_TICK = "reconciler_tick"

# The backup/verify jobs act for the system, not a human (mirrors reconciler).
_SYSTEM_ACTOR = "system:scheduler"


def _credentials_for(device: Device) -> Credentials:
    if device.encrypted_credentials is None:
        return Credentials()
    vault = FernetCredVault.from_settings()
    return deserialize_credentials(device.encrypted_credentials, vault)


async def _all_devices() -> list[Device]:
    """Snapshot every device in its own short-lived session."""
    async with async_session_factory() as session:
        rows = await session.scalars(select(Device).order_by(Device.name))
        return list(rows.all())


# --------------------------------------------------------------------------- #
# Job 1: reachability poll
# --------------------------------------------------------------------------- #
async def poll_reachability() -> None:
    """Probe each device's reachability and update the in-mem map.

    A per-device probe failure (timeout, auth, network) marks the device
    unreachable — it is never allowed to crash the job or the batch.
    """
    settings = get_settings()
    try:
        devices = await _all_devices()
    except Exception:
        logger.exception("poll_reachability: failed to load devices")
        return

    for device in devices:
        checked_at = dt.datetime.now(tz=dt.UTC)
        reachable = False
        try:
            driver = driver_for(device, _credentials_for(device))
            reachable = await asyncio.wait_for(
                driver.reachable(),
                timeout=settings.reachability_timeout_seconds,
            )
        except Exception as exc:
            logger.debug("poll_reachability: %s unreachable: %s", device.name, exc)
            reachable = False
        reachability.record(device.id, reachable=reachable, checked_at=checked_at)


# --------------------------------------------------------------------------- #
# Job 2: nightly config backup
# --------------------------------------------------------------------------- #
async def nightly_backup() -> None:
    """Back up every device's config to a ConfigBackup row + audit entry.

    One device failing (unreachable, driver error) is logged and skipped; the
    batch continues. Each device's persist is its own session/transaction so a
    failure mid-batch never rolls back already-saved backups.
    """
    try:
        devices = await _all_devices()
    except Exception:
        logger.exception("nightly_backup: failed to load devices")
        return

    saved = 0
    for device in devices:
        try:
            async with async_session_factory() as session:
                driver = driver_for(device, _credentials_for(device))
                config_text = await driver.backup_config()
                session.add(
                    ConfigBackup(
                        device_id=device.id,
                        config_text=config_text,
                        fetched_at=dt.datetime.now(tz=dt.UTC),
                        fetched_by=_SYSTEM_ACTOR,
                    )
                )
                await audit.append_audit(
                    session,
                    user_id=None,
                    action="device.backup",
                    target_device_id=device.id,
                    after={"bytes": len(config_text)},
                    result="ok",
                )
                await session.commit()
                saved += 1
        except Exception:
            logger.exception("nightly_backup: backup failed for device %s", device.name)
    logger.info("nightly_backup: %d/%d device backups saved", saved, len(devices))


# --------------------------------------------------------------------------- #
# Job 3: nightly audit-chain verify
# --------------------------------------------------------------------------- #
async def verify_audit_chain() -> None:
    """Walk the audit hash chain; a break logs CRITICAL + a structured alert.

    No auto-repair: a broken chain is tamper evidence and must be loud, not
    silently healed (principal-engineering D6).
    """
    try:
        async with async_session_factory() as session:
            ok, broken_index = await verify_chain(session)
    except Exception:
        logger.exception("verify_audit_chain: verification raised")
        return

    if ok:
        logger.info("verify_audit_chain: audit chain intact")
        return

    # Structured alert — tamper evidence. Surfaces in logs for ops to action.
    logger.critical(
        "AUDIT CHAIN BROKEN — tamper evidence at row index %s. No auto-repair. alert=%s",
        broken_index,
        {"event": "audit_chain_break", "broken_index": broken_index},
    )


# --------------------------------------------------------------------------- #
# Scheduler assembly
# --------------------------------------------------------------------------- #
def build_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    """Configure and return the scheduler (NOT started — caller starts it).

    Registers the four jobs with stable ids and the configured triggers. The
    caller (FastAPI lifespan) is responsible for ``start()`` / ``shutdown()``.
    """
    cfg = settings if settings is not None else get_settings()
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        poll_reachability,
        trigger=IntervalTrigger(seconds=cfg.poll_interval_seconds),
        id=JOB_POLL_REACHABILITY,
        name="reachability poll",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        nightly_backup,
        trigger=CronTrigger.from_crontab(cfg.nightly_backup_cron),
        id=JOB_NIGHTLY_BACKUP,
        name="nightly config backup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        verify_audit_chain,
        trigger=CronTrigger.from_crontab(cfg.audit_verify_cron),
        id=JOB_VERIFY_AUDIT_CHAIN,
        name="audit chain verify",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        reconciler.reconciler_tick,
        trigger=IntervalTrigger(seconds=cfg.reconciler_interval_seconds),
        id=JOB_RECONCILER_TICK,
        name="reconciler tick",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
