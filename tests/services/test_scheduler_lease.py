"""SchedulerLease: single-leader election for the background scheduler.

The Postgres advisory-lock path is exercised with a fake engine/connection (no
live Postgres needed); the SQLite/non-Postgres path is exercised against the
real in-memory test engine. A fake scheduler stands in for APScheduler so no
real timers ever start.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from northbound.config import Settings
from northbound.services.scheduler_lease import SchedulerLease

pytestmark = pytest.mark.asyncio


class _FakeScheduler:
    """Minimal stand-in for AsyncIOScheduler — records start/shutdown, no timers."""

    def __init__(self) -> None:
        self.started = False
        self.shutdown_called = False

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_called = True

    def get_jobs(self) -> list[object]:
        return [object(), object()]


class _FakeResult:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class _FakeConn:
    """Tracks open/close and returns a scripted advisory-lock result."""

    def __init__(self, granted: bool) -> None:
        self._granted = granted
        self.closed = False

    async def execute(self, _stmt: object, _params: object) -> _FakeResult:
        return _FakeResult(self._granted)

    async def close(self) -> None:
        self.closed = True


class _FakeDialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakePostgresEngine:
    """Hands out scripted connections; mimics a Postgres engine's dialect name."""

    def __init__(self, grants: list[bool]) -> None:
        self.dialect = _FakeDialect("postgresql")
        self._grants = list(grants)
        self.conns: list[_FakeConn] = []

    async def connect(self) -> _FakeConn:
        granted = self._grants.pop(0)
        conn = _FakeConn(granted)
        self.conns.append(conn)
        return conn


def _fast_settings() -> Settings:
    # Tiny retry so the failover test doesn't wait the 15s default.
    return Settings(scheduler_lock_retry_seconds=1, enable_scheduler=True)


async def _wait_leader(lease: SchedulerLease, *, timeout: float = 3.0) -> bool:
    """Poll until the lease becomes leader or the timeout elapses."""
    deadline = timeout
    while deadline > 0:
        if lease.is_leader:
            return True
        await asyncio.sleep(0.02)
        deadline -= 0.02
    return lease.is_leader


async def _drain(lease: SchedulerLease) -> None:
    """Wait for one acquisition pass, then stop the lease."""
    await _wait_leader(lease)
    await lease.stop()


async def test_sqlite_is_always_leader(db_engine: AsyncEngine) -> None:
    """Non-Postgres = single process: lease wins immediately, no lock taken."""
    built: list[_FakeScheduler] = []

    def factory(_s: Settings) -> _FakeScheduler:
        sched = _FakeScheduler()
        built.append(sched)
        return sched

    lease = SchedulerLease(db_engine, _fast_settings(), scheduler_factory=factory)
    await lease.start()
    await _drain(lease)

    assert len(built) == 1
    assert built[0].started is True
    assert built[0].shutdown_called is True  # stop() shut it down


async def test_scheduler_built_once(db_engine: AsyncEngine) -> None:
    """Repeated loop ticks must not build/start a second scheduler."""
    built: list[_FakeScheduler] = []
    lease = SchedulerLease(
        db_engine,
        _fast_settings(),
        scheduler_factory=lambda _s: built.append(_FakeScheduler()) or built[-1],
    )
    await lease.start()
    # Let several loop iterations run.
    for _ in range(5):
        await asyncio.sleep(0)
    await lease.stop()
    assert len(built) == 1


async def test_postgres_acquires_lock_and_holds_connection() -> None:
    """Granted advisory lock → leader, and the lock connection stays open."""
    engine = _FakePostgresEngine(grants=[True])
    lease = SchedulerLease(
        engine,  # type: ignore[arg-type]
        _fast_settings(),
        scheduler_factory=lambda _s: _FakeScheduler(),
    )
    await lease.start()
    await _drain(lease)

    assert len(engine.conns) == 1
    # Connection held open while leader; closed only by stop().
    assert engine.conns[0].closed is True  # stop() released it


async def test_postgres_not_leader_closes_connection_and_retries() -> None:
    """Denied lock → not leader, the probe connection is closed, then retried."""
    # First probe denied, second granted (simulates the prior leader dying).
    engine = _FakePostgresEngine(grants=[False, True])
    built: list[_FakeScheduler] = []
    lease = SchedulerLease(
        engine,  # type: ignore[arg-type]
        _fast_settings(),
        scheduler_factory=lambda _s: built.append(_FakeScheduler()) or built[-1],
    )
    await lease.start()
    # First probe is denied: wait until that probe connection exists + is closed.
    for _ in range(50):
        if engine.conns and engine.conns[0].closed:
            break
        await asyncio.sleep(0.02)
    assert engine.conns[0].closed is True  # denied probe was closed
    # The retry interval (1s) then elapses and the second (granted) probe runs.
    assert await _wait_leader(lease, timeout=3.0)
    await lease.stop()
    assert len(built) == 1


async def test_start_failure_releases_lock_and_retries() -> None:
    """If scheduler start throws, the advisory lock must be released (so failover
    works) and the loop must retry — not die while holding the lock."""
    engine = _FakePostgresEngine(grants=[True, True])
    calls = {"n": 0}

    def factory(_s: Settings) -> _FakeScheduler:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("scheduler failed to start")
        return _FakeScheduler()

    lease = SchedulerLease(engine, _fast_settings(), scheduler_factory=factory)  # type: ignore[arg-type]
    await lease.start()
    # First acquire succeeds, start raises → lock released (conn0 closed), not leader.
    for _ in range(50):
        if engine.conns and engine.conns[0].closed:
            break
        await asyncio.sleep(0.02)
    assert engine.conns[0].closed is True
    # Next tick re-acquires and the second start succeeds → leader.
    assert await _wait_leader(lease, timeout=3.0)
    await lease.stop()
    assert calls["n"] >= 2
