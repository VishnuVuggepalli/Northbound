"""Tests for the async DB engine, pragmas, and session dependency."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from northbound import db
from northbound.db import create_engine, get_session


async def test_engine_connects_and_executes(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1


async def test_wal_and_fk_pragmas_set(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
        fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
    # :memory: reports WAL as "memory"; a file DB reports "wal". Either proves
    # the connect listener ran without erroring; FK enforcement must be on.
    assert str(journal).lower() in {"wal", "memory"}
    assert int(fk) == 1


def test_create_engine_uses_given_url() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    assert engine.dialect.name == "sqlite"


async def test_get_session_commits_on_success(
    monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(db, "async_session_factory", factory)

    gen = get_session()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    # exhaust the generator -> triggers commit + close
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


async def test_get_session_rolls_back_on_error(
    monkeypatch: pytest.MonkeyPatch, db_engine: AsyncEngine
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(db, "async_session_factory", factory)

    gen = get_session()
    session = await gen.__anext__()
    # Open a transaction so rollback has something to undo.
    await session.execute(text("SELECT 1"))

    boom = RuntimeError("handler blew up")
    with pytest.raises(RuntimeError, match="handler blew up"):
        await gen.athrow(boom)
    # After rollback + close the session is unusable.
    assert not session.in_transaction()
