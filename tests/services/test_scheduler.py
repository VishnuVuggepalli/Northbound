"""Scheduler assembly + job-body tests.

We never start real APScheduler timers. ``build_scheduler`` is inspected for
the four jobs; job bodies are awaited directly with the in-memory session
factory monkeypatched in. The lifespan guard is asserted to keep the scheduler
OFF when ``enable_scheduler=False`` (so the suite never hangs on live timers).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northbound.config import Settings
from northbound.main import lifespan
from northbound.models.config_backup import ConfigBackup
from northbound.models.device import Device
from northbound.models.enums import DeviceRole
from northbound.services import audit, reachability, reconciler, scheduler
from northbound.services.scheduler import (
    JOB_NIGHTLY_BACKUP,
    JOB_POLL_REACHABILITY,
    JOB_RECONCILER_TICK,
    JOB_VERIFY_AUDIT_CHAIN,
    build_scheduler,
    nightly_backup,
    verify_audit_chain,
)


@pytest.fixture(autouse=True)
def _reset_reachability() -> Iterator[None]:
    reachability.clear()
    yield
    reachability.clear()


@pytest_asyncio.fixture
async def patched_factory(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Point the jobs' own-session factory at the in-memory test engine.

    The jobs call ``async_session_factory()`` (the module-level production
    factory). We swap it in the scheduler + reconciler + audit modules so a job
    opens a session against the test DB, not the real SQLite file.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler, "async_session_factory", factory)
    monkeypatch.setattr(reconciler, "async_session_factory", factory)
    yield factory


# --------------------------------------------------------------------------- #
# build_scheduler
# --------------------------------------------------------------------------- #
def test_build_scheduler_registers_four_jobs() -> None:
    """All four jobs present with the expected ids and trigger types."""
    sched = build_scheduler(Settings(enable_scheduler=True))
    jobs = {j.id: j for j in sched.get_jobs()}

    assert set(jobs) == {
        JOB_POLL_REACHABILITY,
        JOB_NIGHTLY_BACKUP,
        JOB_VERIFY_AUDIT_CHAIN,
        JOB_RECONCILER_TICK,
    }
    assert isinstance(jobs[JOB_POLL_REACHABILITY].trigger, IntervalTrigger)
    assert isinstance(jobs[JOB_RECONCILER_TICK].trigger, IntervalTrigger)
    assert isinstance(jobs[JOB_NIGHTLY_BACKUP].trigger, CronTrigger)
    assert isinstance(jobs[JOB_VERIFY_AUDIT_CHAIN].trigger, CronTrigger)


def test_build_scheduler_honours_configured_intervals() -> None:
    """Interval triggers reflect the configured cadences."""
    cfg = Settings(poll_interval_seconds=42, reconciler_interval_seconds=7)
    sched = build_scheduler(cfg)
    jobs = {j.id: j for j in sched.get_jobs()}

    poll = jobs[JOB_POLL_REACHABILITY].trigger
    tick = jobs[JOB_RECONCILER_TICK].trigger
    assert isinstance(poll, IntervalTrigger)
    assert isinstance(tick, IntervalTrigger)
    assert poll.interval.total_seconds() == 42
    assert tick.interval.total_seconds() == 7


# --------------------------------------------------------------------------- #
# lifespan guard (scheduler OFF in tests)
# --------------------------------------------------------------------------- #
async def test_lifespan_does_not_start_scheduler_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enable_scheduler=False → build_scheduler is never called (no timers)."""
    called = False

    def _spy(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("build_scheduler must not run when disabled")

    monkeypatch.setattr("northbound.main.build_scheduler", _spy)
    monkeypatch.setattr("northbound.main.get_settings", lambda: Settings(enable_scheduler=False))

    async with lifespan(None):  # type: ignore[arg-type]  (app unused by the guard)
        pass
    assert called is False


# --------------------------------------------------------------------------- #
# nightly_backup
# --------------------------------------------------------------------------- #
async def test_nightly_backup_creates_backup_per_device(
    db_session: AsyncSession,
    mock_device: Device,
    patched_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A ConfigBackup row + audit entry is written for the device."""
    await db_session.commit()
    await nightly_backup()

    async with patched_factory() as s:
        count = await s.scalar(
            select(func.count())
            .select_from(ConfigBackup)
            .where(ConfigBackup.device_id == mock_device.id)
        )
        assert count == 1


async def test_nightly_backup_one_failure_does_not_abort_batch(
    db_session: AsyncSession,
    mock_device: Device,
    patched_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A device that can't be backed up is skipped; healthy ones still save."""
    # Second device on an unknown platform → driver_for raises KeyError, which
    # the job swallows per-device. The mock device must still be backed up.
    broken = Device(
        name="broken-box",
        environment="lab",
        platform="does_not_exist",
        role=DeviceRole.LEAF,
        mgmt_ip="10.0.0.99",
        prefer_native_api=True,
        encrypted_credentials=None,
    )
    db_session.add(broken)
    await db_session.commit()

    # Must not raise despite the broken device.
    await nightly_backup()

    async with patched_factory() as s:
        good = await s.scalar(
            select(func.count())
            .select_from(ConfigBackup)
            .where(ConfigBackup.device_id == mock_device.id)
        )
        bad = await s.scalar(
            select(func.count())
            .select_from(ConfigBackup)
            .where(ConfigBackup.device_id == broken.id)
        )
        assert good == 1
        assert bad == 0


# --------------------------------------------------------------------------- #
# verify_audit_chain
# --------------------------------------------------------------------------- #
async def test_verify_audit_chain_clean_no_alert(
    db_session: AsyncSession,
    patched_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An intact chain logs no CRITICAL alert."""
    async with patched_factory() as s:
        await audit.append_audit(s, user_id=None, action="thing.one", result="ok")
        await audit.append_audit(s, user_id=None, action="thing.two", result="ok")
        await s.commit()

    with caplog.at_level("CRITICAL"):
        await verify_audit_chain()
    assert not any(r.levelname == "CRITICAL" for r in caplog.records)


async def test_verify_audit_chain_tampered_logs_critical(
    db_session: AsyncSession,
    patched_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A tampered row → CRITICAL log + structured alert, no auto-repair."""
    from northbound.models.audit_log import AuditLog

    async with patched_factory() as s:
        await audit.append_audit(s, user_id=None, action="thing.one", result="ok")
        row = await audit.append_audit(s, user_id=None, action="thing.two", result="ok")
        # Tamper: mutate the action AFTER the hash was computed → chain breaks.
        tampered = await s.get(AuditLog, row.id)
        assert tampered is not None
        tampered.action = "thing.two.MUTATED"
        s.add(tampered)
        await s.commit()

    with caplog.at_level("CRITICAL"):
        await verify_audit_chain()

    criticals = [r for r in caplog.records if r.levelname == "CRITICAL"]
    assert len(criticals) == 1
    assert "AUDIT CHAIN BROKEN" in criticals[0].getMessage()
