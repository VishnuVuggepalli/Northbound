"""runtime_settings.refresh_loop: cross-worker cache convergence.

A setting changed in the DB by one worker must propagate to every other
worker's in-memory cache within the refresh window. We simulate the "other
worker" by mutating the DB directly, leaving this process's cache stale, then
running one refresh tick and asserting the cache caught up.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from northbound.services import runtime_settings
from northbound.services.runtime_settings import WRITE_RATE_LIMIT_KEY

pytestmark = pytest.mark.asyncio


async def test_refresh_loop_reloads_changed_value(db_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # "Another worker" persists a new value straight to the DB.
    async with factory() as session, session.begin():
        await runtime_settings.set_value(
            session, WRITE_RATE_LIMIT_KEY, "7/minute", updated_by="other-worker"
        )

    # This process's cache is stale (never saw that write-through).
    runtime_settings._cache[WRITE_RATE_LIMIT_KEY] = "30/minute"
    assert runtime_settings.current_write_rate_limit() == "30/minute"

    stop = asyncio.Event()
    task = asyncio.create_task(runtime_settings.refresh_loop(factory, 0.02, stop))
    try:
        for _ in range(50):
            if runtime_settings.current_write_rate_limit() == "7/minute":
                break
            await asyncio.sleep(0.02)
    finally:
        stop.set()
        await task

    assert runtime_settings.current_write_rate_limit() == "7/minute"


async def test_refresh_loop_stops_promptly(db_engine: AsyncEngine) -> None:
    """A long interval must not block shutdown — stop() wakes the wait at once."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    stop = asyncio.Event()
    task = asyncio.create_task(runtime_settings.refresh_loop(factory, 3600, stop))
    await asyncio.sleep(0.02)
    stop.set()
    # Should return well within the 3600s interval.
    await asyncio.wait_for(task, timeout=2.0)
    assert task.done()
