"""Tests for Accept-header API versioning (X-API-Version + 406 on mismatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from northbound.api.versioning import API_VERSION
from northbound.main import app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_stamps_version_header(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["X-API-Version"] == API_VERSION


@pytest.mark.asyncio
async def test_unpinned_accept_served_v1(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    assert resp.headers["X-API-Version"] == API_VERSION


@pytest.mark.asyncio
async def test_pinned_current_version_ok(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"Accept": "application/vnd.northbound.v1+json"})
    assert resp.status_code == 200
    assert resp.headers["X-API-Version"] == API_VERSION


@pytest.mark.asyncio
async def test_pinned_unsupported_version_406(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"Accept": "application/vnd.northbound.v2+json"})
    assert resp.status_code == 406
    assert resp.headers["X-API-Version"] == API_VERSION
    assert "v2" in resp.json()["detail"]
