"""Tests for the append-only, hash-chained audit log (D6)."""

from __future__ import annotations

import asyncio

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


# --------------------------------------------------------------------------- #
# AUD-4: _redact must recurse into list/tuple elements, not only dict values.
# --------------------------------------------------------------------------- #
def test_redact_recurses_into_lists() -> None:
    out = audit._redact({"items": [{"password": "p"}, {"api_token": "t"}, {"keep": "me"}]})
    assert out is not None
    items = out["items"]
    assert items[0] == {"password": "[REDACTED]"}
    assert items[1] == {"api_token": "[REDACTED]"}
    assert items[2] == {"keep": "me"}


def test_redact_recurses_into_nested_list_of_lists() -> None:
    out = audit._redact({"outer": [[{"secret": "s"}], {"username": "bob"}]})
    assert out is not None
    assert out["outer"][0][0] == {"secret": "[REDACTED]"}
    assert out["outer"][1] == {"username": "bob"}


def test_redact_passes_scalar_list_elements_through() -> None:
    out = audit._redact({"vlans": [1, 2, 3], "name": "leaf"})
    assert out == {"vlans": [1, 2, 3], "name": "leaf"}


# --------------------------------------------------------------------------- #
# AUD-3: concurrent appends must not fork the chain.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_concurrent_appends_do_not_fork_chain(db_session: AsyncSession) -> None:
    """Fire several appends concurrently; the chain must stay linear + valid.

    Without the append lock, two coroutines read the same tip, claim the same
    prev_hash, and fork → verify_chain reports a break. The lock serializes the
    read-tip → build → flush section so the tip is always stable.
    """

    async def _one(i: int) -> None:
        await audit.append_audit(
            db_session,
            user_id=None,
            action=f"concurrent.{i}",
            after={"i": i},
            result="ok",
        )

    await asyncio.gather(*[_one(i) for i in range(8)])
    await db_session.flush()

    ok, index = await audit.verify_chain(db_session)
    assert ok is True, f"chain forked at index {index}"
    assert index is None

    rows = (await db_session.scalars(select(AuditLog).order_by(AuditLog.created_at.asc()))).all()
    assert len(rows) == 8
    # Every prev_hash links to the previous row's row_hash (no two share a tip).
    prev_hashes = [r.prev_hash for r in rows]
    assert prev_hashes[0] == audit.GENESIS
    assert len(set(prev_hashes)) == len(prev_hashes)  # no duplicate prev_hash → no fork


# --------------------------------------------------------------------------- #
# AUD-1: the chain must verify after a REAL onboard + full request lifecycle.
# Previously onboard/offboard wrote AuditLog rows with row_hash="" directly,
# breaking verify_chain at the first onboard and re-rooting later appends.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_chain_valid_after_onboard_and_request_lifecycle(
    db_session: AsyncSession,
) -> None:
    import northbound.drivers.mock  # noqa: F401  (registers the mock platform)
    from northbound.auth.password import hash_password
    from northbound.drivers.factory import driver_from_params
    from northbound.models.device import Device
    from northbound.models.enums import DeviceRole, Environment, UserRole
    from northbound.models.user import User
    from northbound.schemas.driver import ConnectionParams, Credentials, PortChange
    from northbound.services import change_apply, requests
    from northbound.services.credvault import FernetCredVault
    from northbound.services.onboarding import onboard_device

    admin = User(username="adm", password_hash=hash_password("a"), role=UserRole.ADMIN)
    alice = User(username="al", password_hash=hash_password("b"), role=UserRole.REQUESTER)
    db_session.add_all([admin, alice])
    await db_session.flush()

    creds = Credentials(username="admin", password="switch-pw")
    driver = driver_from_params("mock", ConnectionParams(host="10.0.0.9"), creds)
    discovery = await driver.discover()
    vault = FernetCredVault.from_settings()

    # Real onboard: device + ports + backup + chained audit row.
    device: Device = await onboard_device(
        db_session,
        name="lab-leaf-chain",
        environment=Environment.LAB,
        role=DeviceRole.LEAF,
        platform_id="mock",
        mgmt_ip="10.0.0.9",
        ssh_user="admin",
        prefer_native_api=True,
        creds=creds,
        discovery=discovery,
        vault=vault,
        actor_user_id=admin.id,
    )

    # Chain is already valid right after onboard (the regression target).
    ok, index = await audit.verify_chain(db_session)
    assert ok is True, f"chain broke at index {index} immediately after onboard"

    # Full request lifecycle against the mock (commit-confirm platform).
    port_name = discovery.ports[0].name
    req = await requests.create_request(
        db_session,
        device=device,
        port_name=port_name,
        requested_changes=PortChange(untagged_vlan=200),
        reason="lifecycle test",
        user=alice,
    )
    await requests.approve_request(db_session, req, admin)
    req = await change_apply.apply_request(db_session, req, device, admin)
    if req.confirm_token:  # commit-confirm platform → confirm to reach applied
        await change_apply.confirm_request(db_session, req, device, admin)

    # The chain must still verify across onboard + created + applied + confirmed.
    ok, index = await audit.verify_chain(db_session)
    assert ok is True, f"chain broke at index {index} after full lifecycle"
    assert index is None

    # Sanity: the onboard row carries a real (non-empty) row_hash, not "".
    onboard_row = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "device.onboarded")
    )
    assert onboard_row is not None
    assert onboard_row.row_hash != ""
    assert onboard_row.prev_hash == audit.GENESIS
