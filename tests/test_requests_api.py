"""HTTP tests for the requests + audit API surface.

Full lifecycle over the wire: create → approve → apply → confirm, plus mine /
status filters and the audit list. Uses the in-mem DB + MockDriver (which is a
commit-confirm platform).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("NB_SECRET_KEY", "unit-test-secret-key")
os.environ.setdefault("NB_MASTER_KEY", "wDPYj3kZ3qbY8m0v6m2nQ1rJf7xq9o5xS3uVc8nH0cE=")

from northbound.auth.jwt import create_access_token
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.main import app
from northbound.models.device import Device
from northbound.models.enums import DeviceRole, UserRole
from northbound.models.user import User
from northbound.schemas.driver import Credentials
from northbound.services import port_state
from northbound.services.credvault import FernetCredVault, serialize_credentials

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    port_state._cache.clear()
    yield
    port_state._cache.clear()


@pytest_asyncio.fixture
async def seeded(
    db_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncSession, User, User, Device, Device]]:
    vault = FernetCredVault.from_settings()
    admin = User(username="admin", password_hash=hash_password("a"), role=UserRole.ADMIN)
    alice = User(username="alice", password_hash=hash_password("b"), role=UserRole.REQUESTER)
    leaf = Device(
        name="lab-leaf",
        environment="lab",
        platform="mock",
        role=DeviceRole.LEAF,
        mgmt_ip="10.0.0.5",
        prefer_native_api=True,
        encrypted_credentials=serialize_credentials(Credentials(username="u"), vault),
    )
    router = Device(
        name="core-router",
        environment="dc",
        platform="mock",
        role=DeviceRole.ROUTER,
        mgmt_ip="10.0.0.1",
        prefer_native_api=True,
        encrypted_credentials=serialize_credentials(Credentials(username="u"), vault),
    )
    db_session.add_all([admin, alice, leaf, router])
    await db_session.flush()
    yield db_session, admin, alice, leaf, router


@pytest_asyncio.fixture
async def client(
    seeded: tuple[AsyncSession, User, User, Device, Device],
) -> AsyncIterator[AsyncClient]:
    session = seeded[0]

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(sub=user.id, role=user.role, settings=get_settings())
    return {"Authorization": f"Bearer {token}"}


def _create_body(device_id: str, port: str = "Ethernet1", vlan: int = 200) -> dict[str, object]:
    return {
        "device_id": device_id,
        "port_name": port,
        "requested_changes": {"untagged_vlan": vlan},
        "reason": "put on vlan 200",
    }


@pytest.mark.asyncio
async def test_full_lifecycle_create_approve_apply_confirm(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    _, admin, alice, leaf, _ = seeded

    created = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    assert created.status_code == 201
    req_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    approved = await client.post(f"/api/requests/{req_id}/approve", headers=_bearer(admin))
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    applied = await client.post(f"/api/requests/{req_id}/apply", headers=_bearer(admin))
    assert applied.status_code == 200
    body = applied.json()
    assert body["status"] == "awaiting_confirm"
    # SEC-2: the raw confirm_token must never cross the HTTP boundary; the DTO
    # exposes only a derived boolean + the (non-secret) deadline.
    assert "confirm_token" not in body
    assert body["awaiting_confirm"] is True
    assert body["diff_text"]

    confirmed = await client.post(f"/api/requests/{req_id}/confirm", headers=_bearer(admin))
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "applied"


@pytest.mark.asyncio
async def test_create_against_router_403(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    _, _, alice, _, router = seeded
    resp = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(router.id))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "READ_ONLY_DEVICE"


@pytest.mark.asyncio
async def test_reject_requires_comment(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    _, admin, alice, leaf, _ = seeded
    created = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    req_id = created.json()["id"]
    # Missing comment → 422 (schema) ; empty after strip handled by service → 400.
    bad = await client.post(
        f"/api/requests/{req_id}/reject", headers=_bearer(admin), json={"comment": ""}
    )
    assert bad.status_code == 422
    ok = await client.post(
        f"/api/requests/{req_id}/reject", headers=_bearer(admin), json={"comment": "not now"}
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_apply_non_admin_403(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    _, admin, alice, leaf, _ = seeded
    created = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    req_id = created.json()["id"]
    await client.post(f"/api/requests/{req_id}/approve", headers=_bearer(admin))
    resp = await client.post(f"/api/requests/{req_id}/apply", headers=_bearer(alice))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mine_and_status_filters(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    _, admin, alice, leaf, _ = seeded
    a = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    await client.post(
        "/api/requests", headers=_bearer(admin), json=_create_body(leaf.id, port="Ethernet2")
    )

    mine = await client.get("/api/requests?mine=true", headers=_bearer(alice))
    assert mine.status_code == 200
    assert [r["id"] for r in mine.json()] == [a.json()["id"]]

    pending = await client.get("/api/requests?request_status=pending", headers=_bearer(admin))
    assert len(pending.json()) == 2


@pytest.mark.asyncio
async def test_list_requests_non_admin_only_sees_own_regardless_of_mine_flag(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    """SEC-1 IDOR: a requester sees ONLY their own requests, even with ?mine=false.

    alice files two; admin files one. alice's list must contain exactly her two,
    never admin's — whatever she passes for ``mine``.
    """
    _, admin, alice, leaf, _ = seeded
    a1 = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    a2 = await client.post(
        "/api/requests", headers=_bearer(alice), json=_create_body(leaf.id, port="Ethernet2")
    )
    await client.post(
        "/api/requests", headers=_bearer(admin), json=_create_body(leaf.id, port="Ethernet3")
    )
    alice_ids = {a1.json()["id"], a2.json()["id"]}

    for query in ("", "?mine=false", "?mine=true"):
        resp = await client.get(f"/api/requests{query}", headers=_bearer(alice))
        assert resp.status_code == 200
        seen = {r["id"] for r in resp.json()}
        # alice's own only — never admin's, even with mine=false.
        assert seen == alice_ids


@pytest.mark.asyncio
async def test_list_requests_admin_sees_all(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    """SEC-1: admin sees every request (alice's + admin's)."""
    _, admin, alice, leaf, _ = seeded
    await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    await client.post(
        "/api/requests", headers=_bearer(admin), json=_create_body(leaf.id, port="Ethernet2")
    )
    resp = await client.get("/api/requests", headers=_bearer(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_request_cross_user_returns_404(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    """SEC-1: alice GETting admin's request id gets 404 (not 403 — no existence leak)."""
    _, admin, alice, leaf, _ = seeded
    others = await client.post("/api/requests", headers=_bearer(admin), json=_create_body(leaf.id))
    other_id = others.json()["id"]

    resp = await client.get(f"/api/requests/{other_id}", headers=_bearer(alice))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_request_owner_and_admin_succeed(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    """SEC-1: the owner reads her own (200); admin reads anyone's (200)."""
    _, admin, alice, leaf, _ = seeded
    created = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    req_id = created.json()["id"]

    owner = await client.get(f"/api/requests/{req_id}", headers=_bearer(alice))
    assert owner.status_code == 200
    as_admin = await client.get(f"/api/requests/{req_id}", headers=_bearer(admin))
    assert as_admin.status_code == 200


@pytest.mark.asyncio
async def test_request_out_never_serializes_confirm_token(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    """SEC-2: even for an awaiting_confirm request, the body has no confirm_token."""
    _, admin, alice, leaf, _ = seeded
    created = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    req_id = created.json()["id"]
    await client.post(f"/api/requests/{req_id}/apply", headers=_bearer(admin))

    detail = await client.get(f"/api/requests/{req_id}", headers=_bearer(admin))
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "awaiting_confirm"
    assert "confirm_token" not in body
    assert body["awaiting_confirm"] is True
    # The token must not leak anywhere in the serialized payload either.
    assert "confirm_token" not in detail.text


@pytest.mark.asyncio
async def test_apply_unapproved_pending_shortcut(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    """Admin approve+apply shortcut: apply a still-pending request directly."""
    _, admin, alice, leaf, _ = seeded
    created = await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    req_id = created.json()["id"]
    applied = await client.post(f"/api/requests/{req_id}/apply", headers=_bearer(admin))
    assert applied.status_code == 200
    assert applied.json()["status"] == "awaiting_confirm"


@pytest.mark.asyncio
async def test_audit_list_filtered(
    client: AsyncClient, seeded: tuple[AsyncSession, User, User, Device, Device]
) -> None:
    _, _, alice, leaf, _ = seeded
    await client.post("/api/requests", headers=_bearer(alice), json=_create_body(leaf.id))
    resp = await client.get(
        f"/api/audit?device_id={leaf.id}&port=Ethernet1", headers=_bearer(alice)
    )
    assert resp.status_code == 200
    actions = [e["action"] for e in resp.json()]
    assert "request.created" in actions
    # No plaintext creds anywhere in the audit feed.
    assert "switch-pw" not in str(resp.json())
