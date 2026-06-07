"""GET /api/events/stream — SSE auth gate + live event delivery."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ["NB_SECRET_KEY"] = "unit-test-secret-key"

from northbound.api.events import event_stream
from northbound.auth.jwt import create_access_token
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.main import app
from northbound.models.enums import UserRole
from northbound.models.user import User
from northbound.services.events import Event, hub

get_settings.cache_clear()

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncClient, User]]:
    admin = User(username="admin", password_hash=hash_password("admin-pw"), role=UserRole.ADMIN)
    db_session.add(admin)
    await db_session.flush()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, admin
    finally:
        app.dependency_overrides.pop(get_session, None)


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(sub=user.id, role=user.role)}"}


async def test_stream_requires_auth(client: tuple[AsyncClient, User]) -> None:
    c, _ = client
    resp = await c.get("/api/events/stream")
    assert resp.status_code == 401


async def test_event_stream_greets_then_forwards_published_events() -> None:
    """The SSE generator emits `hello`, then forwards each hub event as JSON.

    Driven directly (not over the HTTP transport): sse-starlette's wire layer is
    its own tested code; here we verify *our* stream logic deterministically.
    """
    base = hub.subscriber_count  # tolerate subscribers left by other tests
    gen = event_stream()

    # 1) immediate hello, before any subscriber is registered
    hello = await asyncio.wait_for(gen.__anext__(), 1.0)
    assert hello["event"] == "hello"
    assert json.loads(hello["data"]) == {"ok": True}

    # 2) the subscriber registers only once the loop starts; prime the next pull,
    #    wait for registration, then publish.
    nxt = asyncio.create_task(gen.__anext__())
    for _ in range(100):
        if hub.subscriber_count >= 1:
            break
        await asyncio.sleep(0.01)
    assert hub.subscriber_count >= 1
    hub.publish(Event("device.reachability", {"device_id": "dev-9", "reachable": False}))

    # 3) it arrives on the stream, JSON-encoded under its event name
    event = await asyncio.wait_for(nxt, 1.0)
    assert event["event"] == "device.reachability"
    assert json.loads(event["data"]) == {"device_id": "dev-9", "reachable": False}

    await gen.aclose()
    await asyncio.sleep(0)  # let the close cleanup run
    assert hub.subscriber_count == base  # closing the stream deregisters the subscriber
