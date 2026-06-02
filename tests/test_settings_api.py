"""Tests for /api/settings (admin runtime knobs) + the write-endpoint throttle."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ["NB_SECRET_KEY"] = "unit-test-secret-key"

from northbound.api.limiter import limiter, write_rate_limit_provider
from northbound.auth.jwt import create_access_token
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.main import app
from northbound.models.enums import UserRole
from northbound.models.user import User
from northbound.services import runtime_settings

get_settings.cache_clear()


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncSession, User, User]]:
    admin = User(username="admin", password_hash=hash_password("admin-pw"), role=UserRole.ADMIN)
    alice = User(username="alice", password_hash=hash_password("alice-pw"), role=UserRole.REQUESTER)
    db_session.add_all([admin, alice])
    await db_session.flush()
    yield db_session, admin, alice


@pytest_asyncio.fixture
async def client(seeded: tuple[AsyncSession, User, User]) -> AsyncIterator[AsyncClient]:
    session = seeded[0]

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    runtime_settings._cache.clear()  # isolate cache between tests
    limiter.reset()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        runtime_settings._cache.clear()
        limiter.reset()


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user.id, role=user.role)}"}


# --------------------------------------------------------------------------- #
# /api/settings
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_get_settings_returns_default(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    resp = await client.get("/api/settings", headers=_bearer(admin))
    assert resp.status_code == 200
    assert resp.json()["write_rate_limit"] == runtime_settings.default_write_rate_limit()


@pytest.mark.asyncio
async def test_get_settings_requester_forbidden(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, _, alice = seeded
    resp = await client.get("/api/settings", headers=_bearer(alice))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_settings_updates_value_and_cache(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    resp = await client.patch(
        "/api/settings", headers=_bearer(admin), json={"write_rate_limit": "99/minute"}
    )
    assert resp.status_code == 200
    assert resp.json()["write_rate_limit"] == "99/minute"
    # Cache (and therefore the slowapi provider) reflects the change immediately.
    assert runtime_settings.current_write_rate_limit() == "99/minute"
    assert write_rate_limit_provider() == "99/minute"


@pytest.mark.asyncio
async def test_patch_settings_invalid_rate_422(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    resp = await client.patch(
        "/api/settings", headers=_bearer(admin), json={"write_rate_limit": "not-a-rate"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_settings_requester_forbidden(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, _, alice = seeded
    resp = await client.patch(
        "/api/settings", headers=_bearer(alice), json={"write_rate_limit": "5/minute"}
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Write-endpoint throttle (dynamic limit driven by runtime_settings)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_write_endpoint_throttled_by_runtime_limit(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    """With the write limit set low, the (N+1)th write from one user is 429.

    Uses POST /api/users (a throttled write). Each call has a distinct username
    so the limiter — not a 409 — is what stops the run.
    """
    _, admin, _ = seeded
    runtime_settings._cache[runtime_settings.WRITE_RATE_LIMIT_KEY] = "2/minute"
    codes = []
    for i in range(3):
        r = await client.post(
            "/api/users",
            headers=_bearer(admin),
            json={"username": f"u{i}", "password": "x", "role": "requester"},
        )
        codes.append(r.status_code)
    assert codes[:2] == [201, 201]
    assert codes[2] == 429  # third write exceeds 2/minute → throttled


@pytest.mark.asyncio
async def test_write_throttle_is_per_user(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    """Budget is keyed per user: exhausting admin's does not block a fresh user."""
    _, admin, alice = seeded
    runtime_settings._cache[runtime_settings.WRITE_RATE_LIMIT_KEY] = "1/minute"
    first = await client.post(
        "/api/users",
        headers=_bearer(admin),
        json={"username": "x1", "password": "x", "role": "requester"},
    )
    second = await client.post(
        "/api/users",
        headers=_bearer(admin),
        json={"username": "x2", "password": "x", "role": "requester"},
    )
    assert first.status_code == 201
    assert second.status_code == 429  # admin's 1/minute budget exhausted
    # alice is a requester so she'd get 403 (not 429) — proving a separate bucket
    # is evaluated for her key rather than admin's exhausted one.
    alice_resp = await client.post(
        "/api/users",
        headers=_bearer(alice),
        json={"username": "x3", "password": "x", "role": "requester"},
    )
    assert alice_resp.status_code == 403
