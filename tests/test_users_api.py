"""Tests for /api/users/me, list, create + RBAC enforcement."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Pin the signing secret before settings are first read so app-side decode and
# test-side token minting share one key.
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
async def seeded(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncSession, User, User]]:
    """Seed an admin + requester and yield (session, admin, requester)."""
    admin = User(username="admin", password_hash=hash_password("admin-pw"), role=UserRole.ADMIN)
    alice = User(
        username="alice",
        password_hash=hash_password("alice-pw"),
        role=UserRole.REQUESTER,
        email="alice@example.com",
    )
    db_session.add_all([admin, alice])
    await db_session.flush()
    yield db_session, admin, alice


@pytest_asyncio.fixture
async def client(
    seeded: tuple[AsyncSession, User, User],
) -> AsyncIterator[AsyncClient]:
    session = seeded[0]

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def _token(user: User) -> str:
    return create_access_token(sub=user.id, role=user.role, settings=get_settings())


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user)}"}


# --------------------------------------------------------------------------- #
# GET /api/users/me
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_me_with_valid_token(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, _, alice = seeded
    resp = await client.get("/api/users/me", headers=_bearer(alice))
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert body["role"] == "requester"
    assert body["email"] == "alice@example.com"
    assert "password_hash" not in body


@pytest.mark.asyncio
async def test_me_no_token_401(client: AsyncClient) -> None:
    resp = await client.get("/api/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_bad_token_401(client: AsyncClient) -> None:
    resp = await client.get("/api/users/me", headers={"Authorization": "Bearer garbage.token.x"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# GET /api/users (require_admin)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_list_users_requester_forbidden(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, _, alice = seeded
    resp = await client.get("/api/users", headers=_bearer(alice))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_users_admin_ok(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    resp = await client.get("/api/users", headers=_bearer(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert {u["username"] for u in body} == {"admin", "alice"}
    for u in body:
        assert "password_hash" not in u


# --------------------------------------------------------------------------- #
# POST /api/users (require_admin)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_user_as_admin_201_hashed(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    session, admin, _ = seeded
    resp = await client.post(
        "/api/users",
        headers=_bearer(admin),
        json={"username": "bob", "password": "bob-pw", "role": "requester"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "bob"
    assert body["role"] == "requester"
    assert "password_hash" not in body  # never exposed

    # The stored hash is a bcrypt hash, not the plaintext.
    stored = await session.scalar(select(User).where(User.username == "bob"))
    assert stored is not None
    assert stored.password_hash != "bob-pw"
    assert stored.password_hash.startswith("$2")  # bcrypt prefix


@pytest.mark.asyncio
async def test_create_user_duplicate_username_409(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    resp = await client.post(
        "/api/users",
        headers=_bearer(admin),
        json={"username": "alice", "password": "x", "role": "requester"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_user_as_requester_forbidden(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, _, alice = seeded
    resp = await client.post(
        "/api/users",
        headers=_bearer(alice),
        json={"username": "carol", "password": "x", "role": "requester"},
    )
    assert resp.status_code == 403
