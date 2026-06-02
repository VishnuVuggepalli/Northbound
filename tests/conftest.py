"""Shared test fixtures for the DB layer.

Provides an in-memory SQLite engine and an async session. A single shared
connection is reused for the whole engine via ``StaticPool`` so that
``:memory:`` (which is per-connection) keeps the created schema visible to
every session in the test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Importing the package registers every model on Base.metadata.
import northbound.models  # noqa: F401
from northbound.db import Base, _apply_sqlite_pragmas
from northbound.services.sites import ensure_default_sites


@pytest_asyncio.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """In-memory engine with schema created + default sites seeded; dropped on teardown."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Seed default Lab/DC sites so the onboarding flow (which validates the site
    # catalog) works out of the box — mirrors the app's startup seed.
    seed_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with seed_factory() as session, session.begin():
        await ensure_default_sites(session)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session bound to the in-memory engine."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
