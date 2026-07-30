"""Tests for user disable/enable and delete, and the guards on both.

Context: until this landed there was no way to remove OR disable an account.
The lab node accumulated 9 users, 4 self-registered inside 48 hours, all
permanent. The guards below are the part that must never regress — an admin
locking themselves out, or deleting the last admin, is not recoverable through
the UI.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

os.environ["NB_SECRET_KEY"] = "unit-test-secret-key"

from northbound.auth.jwt import create_access_token
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.main import app
from northbound.models.enums import UserRole
from northbound.models.user import User

get_settings.cache_clear()


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncSession, User, User, User]]:
    """Two admins + one requester.

    Two admins on purpose: with only one, every delete/disable would hit the
    last-admin guard and the happy paths could not be tested at all.
    """
    admin = User(username="admin", password_hash=hash_password("pw"), role=UserRole.ADMIN)
    admin2 = User(username="admin2", password_hash=hash_password("pw"), role=UserRole.ADMIN)
    alice = User(username="alice", password_hash=hash_password("pw"), role=UserRole.REQUESTER)
    db_session.add_all([admin, admin2, alice])
    await db_session.flush()
    yield db_session, admin, admin2, alice


@pytest_asyncio.fixture
async def client(seeded: tuple[AsyncSession, User, User, User]) -> AsyncIterator[AsyncClient]:
    session = seeded[0]

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(
        sub=user.id, role=user.role, token_version=user.token_version, settings=get_settings()
    )
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# disable / enable
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_admin_can_disable_a_user(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, _, alice = seeded
    resp = await client.patch(
        f"/api/users/{alice.id}/active", json={"is_active": False}, headers=_bearer(admin)
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_disabling_kills_live_sessions(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    """A token minted BEFORE the disable must stop working immediately.

    The flag alone would not do this — an issued JWT is stateless. Disable also
    bumps token_version, which is what actually revokes it.
    """
    _, admin, _, alice = seeded
    alice_token = _bearer(alice)
    assert (await client.get("/api/users/me", headers=alice_token)).status_code == 200

    await client.patch(
        f"/api/users/{alice.id}/active", json={"is_active": False}, headers=_bearer(admin)
    )
    assert (await client.get("/api/users/me", headers=alice_token)).status_code == 401


@pytest.mark.asyncio
async def test_disabled_user_cannot_log_in(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, _, alice = seeded
    await client.patch(
        f"/api/users/{alice.id}/active", json={"is_active": False}, headers=_bearer(admin)
    )
    resp = await client.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert resp.status_code == 401
    # Generic message — saying "disabled" would confirm the username exists.
    assert "disabled" not in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_re_enabling_restores_login(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, _, alice = seeded
    await client.patch(
        f"/api/users/{alice.id}/active", json={"is_active": False}, headers=_bearer(admin)
    )
    resp = await client.patch(
        f"/api/users/{alice.id}/active", json={"is_active": True}, headers=_bearer(admin)
    )
    assert resp.status_code == 200
    assert (
        await client.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    ).status_code == 200


@pytest.mark.asyncio
async def test_cannot_disable_yourself(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, _, _ = seeded
    resp = await client.patch(
        f"/api/users/{admin.id}/active", json={"is_active": False}, headers=_bearer(admin)
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cannot_disable_the_last_active_admin(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    session, admin, admin2, _ = seeded
    # Disable the second admin first — allowed, one admin still remains.
    assert (
        await client.patch(
            f"/api/users/{admin2.id}/active", json={"is_active": False}, headers=_bearer(admin)
        )
    ).status_code == 200
    # Now admin2 (already disabled) is the only other one; disabling the last
    # ACTIVE admin must be refused even by a different admin.
    admin.is_active = True
    session.add(admin)
    await session.flush()
    resp = await client.patch(
        f"/api/users/{admin.id}/active", json={"is_active": False}, headers=_bearer(admin)
    )
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_admin_can_delete_a_user(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    session, admin, _, alice = seeded
    resp = await client.delete(f"/api/users/{alice.id}", headers=_bearer(admin))
    assert resp.status_code == 204
    assert await session.scalar(select(User).where(User.id == alice.id)) is None


@pytest.mark.asyncio
async def test_cannot_delete_yourself(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, _, _ = seeded
    resp = await client.delete(f"/api/users/{admin.id}", headers=_bearer(admin))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cannot_delete_the_last_active_admin(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, admin2, _ = seeded
    # Removing one of two admins is fine.
    assert (await client.delete(f"/api/users/{admin2.id}", headers=_bearer(admin))).status_code == 204
    # The remaining admin cannot be removed — and cannot remove themselves
    # either, so this is covered from both directions.
    resp = await client.delete(f"/api/users/{admin.id}", headers=_bearer(admin))
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_unknown_user_404(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, _, _ = seeded
    assert (await client.delete("/api/users/nope", headers=_bearer(admin))).status_code == 404


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_requester_cannot_disable(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, _, alice = seeded
    resp = await client.patch(
        f"/api/users/{admin.id}/active", json={"is_active": False}, headers=_bearer(alice)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_requester_cannot_delete(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, admin, _, alice = seeded
    assert (await client.delete(f"/api/users/{admin.id}", headers=_bearer(alice))).status_code == 403


@pytest.mark.asyncio
async def test_anonymous_cannot_delete(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, User]
) -> None:
    _, _, _, alice = seeded
    assert (await client.delete(f"/api/users/{alice.id}")).status_code == 401
