"""Single-leader election for the background scheduler (multi-worker safe).

Only ONE process may run the scheduler. If every uvicorn/gunicorn worker ran it,
the four background jobs (reachability poll, nightly backup, audit-chain verify,
reconciler tick) would each fire once per worker — N times the work, plus
duplicate config backups and contending reconciler writes.

Leadership is elected with a PostgreSQL **session-level advisory lock**
(``pg_try_advisory_lock``) held on a dedicated connection for the lifetime of
the owning process. The lock auto-releases if that process dies, so a surviving
worker takes over on its next acquisition attempt (cadence:
``scheduler_lock_retry_seconds``).

On SQLite — or any non-Postgres backend — there is only ever one process, so the
lease is granted unconditionally and no lock is taken.

The lease is started/stopped by the FastAPI lifespan. It owns the scheduler
object so a non-leader never even builds one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from northbound.config import Settings, get_settings
from northbound.services.scheduler import build_scheduler

logger = logging.getLogger("northbound.services.scheduler_lease")

# Stable 64-bit signed key for pg_try_advisory_lock. Hardcoded (not derived at
# runtime) so it never shifts across releases — a moving key would let two
# versions each believe they hold leadership. Derived once from "NBSCHED1".
_ADVISORY_LOCK_KEY = 0x4E42_5343_4845_4431

# Minimal structural type for the scheduler so tests can inject a fake without
# spinning real APScheduler timers.
SchedulerFactory = Callable[[Settings], object]


class SchedulerLease:
    """Runs the scheduler in exactly one process; retries to take over on failover.

    ``scheduler_factory`` defaults to the production :func:`build_scheduler`; a
    test injects a fake to avoid live timers. The returned object must expose
    ``start()``, ``shutdown(wait: bool)`` and ``get_jobs()``.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings | None = None,
        *,
        scheduler_factory: SchedulerFactory = build_scheduler,
    ) -> None:
        self._engine = engine
        self._settings = settings or get_settings()
        self._scheduler_factory = scheduler_factory
        self._is_postgres = engine.dialect.name == "postgresql"
        self._lock_conn: AsyncConnection | None = None
        self._scheduler: object | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def is_leader(self) -> bool:
        """True once this process owns the scheduler."""
        return self._scheduler is not None

    async def start(self) -> None:
        """Begin the acquire-and-run loop (returns immediately)."""
        self._task = asyncio.create_task(self._run(), name="scheduler-lease")

    async def _run(self) -> None:
        interval = self._settings.scheduler_lock_retry_seconds
        while not self._stop.is_set():
            if self._scheduler is None and await self._acquire():
                self._start_scheduler()
            # Wait out the retry interval, but wake immediately on stop().
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                continue

    def _start_scheduler(self) -> None:
        scheduler = self._scheduler_factory(self._settings)
        scheduler.start()  # type: ignore[attr-defined]
        self._scheduler = scheduler
        job_count = len(scheduler.get_jobs())  # type: ignore[attr-defined]
        logger.info("scheduler leadership acquired; %d job(s) running", job_count)

    async def _acquire(self) -> bool:
        """Try to become leader. Non-Postgres: always wins (single process)."""
        if not self._is_postgres:
            return True
        conn = await self._engine.connect()
        try:
            got = (
                await conn.execute(
                    text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            ).scalar()
        except Exception:
            logger.warning("advisory-lock acquisition failed; will retry", exc_info=True)
            await conn.close()
            return False
        if got:
            # Hold the connection open for the process lifetime: the advisory
            # lock is bound to this DB session and releases when it closes.
            self._lock_conn = conn
            return True
        await conn.close()
        return False

    async def stop(self) -> None:
        """Stop the loop, shut the scheduler down, and release the lock."""
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)  # type: ignore[attr-defined]
            self._scheduler = None
        if self._lock_conn is not None:
            # Explicitly unlock before closing: AsyncConnection.close() returns
            # the connection to the pool ALIVE, so the session-scoped advisory
            # lock would otherwise stay held and no other worker could take over.
            # (A crashed process needs no unlock — the OS closes its socket and
            # Postgres releases the lock when the session ends.)
            try:
                await self._lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": _ADVISORY_LOCK_KEY},
                )
            except Exception:
                logger.warning("advisory-lock release failed", exc_info=True)
            await self._lock_conn.close()
            self._lock_conn = None
