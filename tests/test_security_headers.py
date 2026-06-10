"""SecurityHeadersMiddleware: response headers + cross-origin write guard."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("NB_SECRET_KEY", "unit-test-secret-key")

from fastapi import FastAPI

from northbound.api.security_headers import SecurityHeadersMiddleware, _origin_allowed


def _app(
    *,
    enforce: bool = True,
    hsts: bool = False,
    allowed: frozenset[str] = frozenset(),
) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/write")
    async def write() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        SecurityHeadersMiddleware,
        enforce_origin=enforce,
        hsts=hsts,
        extra_allowed=allowed,
    )
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_headers_stamped_on_responses() -> None:
    async with _client(_app()) as c:
        resp = await c.get("/ping")
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in resp.headers["content-security-policy"]
    assert "strict-transport-security" not in resp.headers  # hsts=False


@pytest.mark.asyncio
async def test_hsts_only_when_secure_deployment() -> None:
    async with _client(_app(hsts=True)) as c:
        resp = await c.get("/ping")
    assert "max-age" in resp.headers["strict-transport-security"]


@pytest.mark.asyncio
async def test_cross_origin_write_rejected() -> None:
    async with _client(_app(enforce=True)) as c:
        resp = await c.post("/write", headers={"origin": "https://evil.example"})
    assert resp.status_code == 403
    # The rejection itself still carries the security headers.
    assert resp.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_same_origin_write_allowed() -> None:
    async with _client(_app(enforce=True)) as c:
        resp = await c.post("/write", headers={"origin": "http://testserver"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_allowlisted_origin_write_allowed() -> None:
    async with _client(_app(enforce=True, allowed=frozenset({"https://nb.corp"}))) as c:
        resp = await c.post("/write", headers={"origin": "https://nb.corp"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_write_without_origin_allowed() -> None:
    """API clients (curl, scripts) send no Origin — they must pass."""
    async with _client(_app(enforce=True)) as c:
        resp = await c.post("/write")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cross_origin_get_allowed() -> None:
    """Only state-changing methods are guarded; reads pass (no CSRF surface)."""
    async with _client(_app(enforce=True)) as c:
        resp = await c.get("/ping", headers={"origin": "https://evil.example"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_development_skips_origin_enforcement() -> None:
    """The Vite dev proxy rewrites Host (changeOrigin) — enforcement would
    false-positive every dev write, so development passes enforce=False."""
    async with _client(_app(enforce=False)) as c:
        resp = await c.post("/write", headers={"origin": "http://localhost:5173"})
    assert resp.status_code == 200


def test_origin_allowed_matrix() -> None:
    allowed = frozenset({"https://nb.corp"})
    assert _origin_allowed("https://nb.corp", "other-host", allowed)  # allowlist
    assert _origin_allowed("http://h:8090", "h:8090", frozenset())  # same-origin
    assert not _origin_allowed("https://evil.example", "h:8090", frozenset())
    assert not _origin_allowed("null", "h:8090", frozenset())  # sandboxed iframe
    assert not _origin_allowed("https://evil.example", None, frozenset())
