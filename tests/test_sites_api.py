"""Tests for the sites catalog API (/api/sites).

Uses the in-memory DB fixtures from ``tests/conftest.py``. The default Lab/DC
sites are seeded by the ``db_engine`` fixture, so the catalog starts populated.
Auth uses real JWTs for a seeded admin / requester.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ["NB_SECRET_KEY"] = "unit-test-secret-key"
os.environ["NB_MASTER_KEY"] = "wDPYj3kZ3qbY8m0v6m2nQ1rJf7xq9o5xS3uVc8nH0cE="

from northbound.auth.jwt import create_access_token
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.main import app
from northbound.models.device import Device
from northbound.models.enums import DeviceRole, UserRole
from northbound.models.user import User

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
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(sub=user.id, role=user.role, settings=get_settings())
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_sites_returns_defaults(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, _, alice = seeded
    resp = await client.get("/api/sites", headers=_bearer(alice))
    assert resp.status_code == 200
    slugs = {s["slug"] for s in resp.json()}
    assert {"lab", "dc"} <= slugs


@pytest.mark.asyncio
async def test_create_site_admin_only(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, alice = seeded
    body = {"slug": "edge-dr", "name": "Edge DR"}

    # requester forbidden
    forbidden = await client.post("/api/sites", headers=_bearer(alice), json=body)
    assert forbidden.status_code == 403

    # admin creates
    created = await client.post("/api/sites", headers=_bearer(admin), json=body)
    assert created.status_code == 201
    assert created.json()["slug"] == "edge-dr"
    assert created.json()["device_count"] == 0

    # now listable
    listed = await client.get("/api/sites", headers=_bearer(alice))
    assert "edge-dr" in {s["slug"] for s in listed.json()}


@pytest.mark.asyncio
async def test_create_site_rejects_bad_slug_and_duplicate(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    bad = await client.post(
        "/api/sites", headers=_bearer(admin), json={"slug": "Bad Slug!", "name": "x"}
    )
    assert bad.status_code == 422  # slug validator rejects

    dup = await client.post(
        "/api/sites", headers=_bearer(admin), json={"slug": "lab", "name": "Dup"}
    )
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_rename_site(client: AsyncClient, seeded: tuple[AsyncSession, User, User]) -> None:
    _, admin, _ = seeded
    created = await client.post(
        "/api/sites", headers=_bearer(admin), json={"slug": "west", "name": "West"}
    )
    site_id = created.json()["id"]
    renamed = await client.patch(
        f"/api/sites/{site_id}", headers=_bearer(admin), json={"name": "West Coast"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "West Coast"
    assert renamed.json()["slug"] == "west"  # slug immutable


@pytest.mark.asyncio
async def test_delete_site_blocked_when_devices_attached(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    session, admin, _ = seeded
    created = await client.post(
        "/api/sites", headers=_bearer(admin), json={"slug": "west", "name": "West"}
    )
    site_id = created.json()["id"]

    # empty site deletes fine
    empty_del = await client.delete(f"/api/sites/{site_id}", headers=_bearer(admin))
    assert empty_del.status_code == 204

    # attach a device to "lab", then deletion of lab is blocked
    session.add(
        Device(
            name="d1", environment="lab", platform="mock", role=DeviceRole.LEAF, mgmt_ip="10.0.0.1"
        )
    )
    await session.flush()
    lab = next(
        s
        for s in (await client.get("/api/sites", headers=_bearer(admin))).json()
        if s["slug"] == "lab"
    )
    assert lab["device_count"] == 1
    blocked = await client.delete(f"/api/sites/{lab['id']}", headers=_bearer(admin))
    assert blocked.status_code == 409


@pytest.mark.asyncio
async def test_onboard_rejects_unknown_site(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User]
) -> None:
    _, admin, _ = seeded
    body = {
        "name": "x-1",
        "environment": "nonexistent-site",
        "role": "leaf",
        "platform_id": "mock",
        "mgmt_ip": "10.0.0.9",
        "credentials": {"username": "u", "password": "p"},
    }
    resp = await client.post("/api/devices", headers=_bearer(admin), json=body)
    assert resp.status_code == 400
    assert "Unknown site" in resp.json()["detail"]
