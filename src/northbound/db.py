"""Async database engine, session factory, and declarative base.

Single-worker SQLite in WAL mode for v1 (see principal-engineering.md D9).
WAL + a short busy timeout + foreign-key enforcement are applied on every
new connection via an engine event listener. Swapping ``db_url`` to Postgres
later requires no API changes — the WAL listener simply no-ops off-SQLite.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from northbound.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _apply_sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:
    """Set WAL, busy timeout, and FK enforcement on each SQLite connection.

    ``dbapi_conn`` is the raw driver connection (aiosqlite's sync-facing
    Connection). It is untyped at the DBAPI boundary, hence ``Any``.
    """
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=100")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_engine(db_url: str | None = None) -> AsyncEngine:
    """Build an async engine, wiring SQLite pragmas when applicable."""
    url = db_url if db_url is not None else get_settings().db_url
    engine = create_async_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    return engine


# Module-level engine + session factory bound to the configured URL.
engine: AsyncEngine = create_engine()

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a session, commit on success, rollback on error.

    The session is always closed. Callers that need explicit transaction
    control can manage commits themselves; the default here is commit-on-exit
    so request handlers don't silently drop writes.
    """
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
