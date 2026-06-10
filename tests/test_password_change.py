"""Password change/reset: self-service + admin reset, with session invalidation.

A password change bumps ``User.token_version``; tokens carry a ``ver`` claim
checked on every request, so a change kills every previously-issued session
(the point of changing a password after compromise). The self-change response
re-issues fresh cookies so the user who changed it stays logged in.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("NB_SECRET_KEY", "unit-test-secret-key")

from northbound.api.limiter import limiter
from northbound.auth.password import hash_password
from northbound.db import get_session
from northbound.main import app
from northbound.models.enums import UserRole
from northbound.models.user import User


@pytest_asyncio.fixture
async def users(db_session: AsyncSession) -> tuple[User, User]:
    admin = User(username="padmin", password_hash=hash_password("admin-pw-1"), role=UserRole.ADMIN)
    alice = User(
        username="palice", password_hash=hash_password("alice-pw-1"), role=UserRole.REQUESTER
    )
    db_session.add_all([admin, alice])
    await db_session.flush()
    return admin, alice


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, users: tuple[User, User]) -> AsyncIterator[AsyncClient]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override
    limiter.reset()  # per-test budget — logins here must not bleed across tests
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        limiter.reset()


async def _login(client: AsyncClient, username: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Self-service: POST /api/users/me/password
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_self_change_requires_correct_current_password(client: AsyncClient) -> None:
    token = await _login(client, "palice", "alice-pw-1")
    resp = await client.post(
        "/api/users/me/password",
        headers=_bearer(token),
        json={"current_password": "WRONG", "new_password": "alice-pw-2-long"},
    )
    assert resp.status_code == 400
    # Old password still works.
    await _login(client, "palice", "alice-pw-1")


@pytest.mark.asyncio
async def test_self_change_rotates_password(client: AsyncClient) -> None:
    token = await _login(client, "palice", "alice-pw-1")
    resp = await client.post(
        "/api/users/me/password",
        headers=_bearer(token),
        json={"current_password": "alice-pw-1", "new_password": "alice-pw-2-long"},
    )
    assert resp.status_code == 200
    # Old password dead; new password works.
    bad = await client.post(
        "/api/auth/login", json={"username": "palice", "password": "alice-pw-1"}
    )
    assert bad.status_code == 401
    await _login(client, "palice", "alice-pw-2-long")


@pytest.mark.asyncio
async def test_self_change_invalidates_old_sessions(client: AsyncClient) -> None:
    old_token = await _login(client, "palice", "alice-pw-1")
    resp = await client.post(
        "/api/users/me/password",
        headers=_bearer(old_token),
        json={"current_password": "alice-pw-1", "new_password": "alice-pw-2-long"},
    )
    assert resp.status_code == 200
    # The response re-issued cookies, so the changing client stays logged in.
    me_cookie = await client.get("/api/users/me")
    assert me_cookie.status_code == 200
    # The pre-change token (ver=0) must be rejected after the bump. Clear the
    # cookie jar first — the (fresh, valid) session cookie outranks the bearer.
    client.cookies.clear()
    me = await client.get("/api/users/me", headers=_bearer(old_token))
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_self_change_rejects_short_password(client: AsyncClient) -> None:
    token = await _login(client, "palice", "alice-pw-1")
    resp = await client.post(
        "/api/users/me/password",
        headers=_bearer(token),
        json={"current_password": "alice-pw-1", "new_password": "short"},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Admin reset: POST /api/users/{user_id}/password-reset
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_admin_reset_kicks_target_sessions(
    client: AsyncClient, users: tuple[User, User]
) -> None:
    _, alice = users
    alice_token = await _login(client, "palice", "alice-pw-1")
    admin_token = await _login(client, "padmin", "admin-pw-1")

    resp = await client.post(
        f"/api/users/{alice.id}/password-reset",
        headers=_bearer(admin_token),
        json={"new_password": "alice-reset-pw-9"},
    )
    assert resp.status_code == 200

    # Target's old password and old session are both dead; new password works.
    bad = await client.post(
        "/api/auth/login", json={"username": "palice", "password": "alice-pw-1"}
    )
    assert bad.status_code == 401
    # Clear the jar (it holds the ADMIN's valid session cookie, which would
    # outrank the stale bearer) before proving alice's old token is dead.
    client.cookies.clear()
    me = await client.get("/api/users/me", headers=_bearer(alice_token))
    assert me.status_code == 401
    await _login(client, "palice", "alice-reset-pw-9")


@pytest.mark.asyncio
async def test_reset_is_admin_only(client: AsyncClient, users: tuple[User, User]) -> None:
    admin, _ = users
    alice_token = await _login(client, "palice", "alice-pw-1")
    resp = await client.post(
        f"/api/users/{admin.id}/password-reset",
        headers=_bearer(alice_token),
        json={"new_password": "evil-reset-pw-9"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reset_unknown_user_404(client: AsyncClient) -> None:
    admin_token = await _login(client, "padmin", "admin-pw-1")
    resp = await client.post(
        "/api/users/nope/password-reset",
        headers=_bearer(admin_token),
        json={"new_password": "whatever-pw-9"},
    )
    assert resp.status_code == 404
