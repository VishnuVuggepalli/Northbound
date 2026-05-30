"""Tests for the append-only, hash-chained audit log (D6)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.models.audit_log import AuditLog
from northbound.services import audit


@pytest.mark.asyncio
async def test_chain_verifies_after_appends(db_session: AsyncSession) -> None:
    for i in range(3):
        await audit.append_audit(
            db_session,
            user_id=None,
            action=f"test.action.{i}",
            after={"i": i},
            result="ok",
        )
    ok, index = await audit.verify_chain(db_session)
    assert ok is True
    assert index is None


@pytest.mark.asyncio
async def test_genesis_prev_hash(db_session: AsyncSession) -> None:
    row = await audit.append_audit(db_session, user_id=None, action="first", result="ok")
    assert row.prev_hash == audit.GENESIS
    assert row.row_hash  # non-empty


@pytest.mark.asyncio
async def test_chain_links_prev_to_row(db_session: AsyncSession) -> None:
    r1 = await audit.append_audit(db_session, user_id=None, action="a", result="ok")
    r2 = await audit.append_audit(db_session, user_id=None, action="b", result="ok")
    assert r2.prev_hash == r1.row_hash


@pytest.mark.asyncio
async def test_tamper_detected_at_correct_index(db_session: AsyncSession) -> None:
    rows = []
    for i in range(3):
        rows.append(
            await audit.append_audit(
                db_session, user_id=None, action=f"act{i}", after={"i": i}, result="ok"
            )
        )
    await db_session.flush()

    # Tamper the middle row's payload without recomputing the hash.
    target = await db_session.scalar(select(AuditLog).where(AuditLog.action == "act1"))
    assert target is not None
    target.after = {"i": 999}
    db_session.add(target)
    await db_session.flush()

    ok, index = await audit.verify_chain(db_session)
    assert ok is False
    assert index == 1


@pytest.mark.asyncio
async def test_credentials_never_in_before_after(db_session: AsyncSession) -> None:
    row = await audit.append_audit(
        db_session,
        user_id=None,
        action="cred.created",
        before={"password": "hunter2", "username": "bob"},
        after={"api_token": "secret-token", "nested": {"snmp_community": "public"}},
        result="ok",
    )
    assert row.before == {"password": "[REDACTED]", "username": "bob"}
    assert row.after is not None
    assert row.after["api_token"] == "[REDACTED]"
    assert row.after["nested"]["snmp_community"] == "[REDACTED]"
    flat = str(row.before) + str(row.after)
    assert "hunter2" not in flat
    assert "secret-token" not in flat
    assert "public" not in flat
