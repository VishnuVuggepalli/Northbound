"""Static SPA serving tests.

Covers the four D9 invariants:
  1. API precedence: /health and /api/* still resolve (not shadowed by the SPA).
  2. SPA fallback: an unknown non-API path returns the index.html shell.
  3. /api/* misses stay a real 404 (JSON), never the HTML shell.
  4. Missing dist: the app still boots and the API still serves.

The fallback cases build a fresh FastAPI app and call ``mount_spa`` against a
temp dist dir (via NB_FRONTEND_DIST), so they don't depend on a real frontend
build being present in the repo.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from northbound.api.static_spa import mount_spa
from northbound.config import get_settings
from northbound.main import app as real_app

_INDEX_HTML = "<!doctype html><html><body><div id=root></div></body></html>"


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    (dist / "favicon.ico").write_text("icon", encoding="utf-8")
    return dist


def _app_with_dist(dist: Path) -> FastAPI:
    """Fresh app with a /health route and the SPA mounted from ``dist``."""
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/platforms")
    async def platforms() -> list[str]:
        return ["mock"]

    mount_spa(app)
    return app


@pytest.fixture
def _dist_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    dist = _make_dist(tmp_path)
    monkeypatch.setenv("NB_FRONTEND_DIST", str(dist))
    get_settings.cache_clear()
    yield dist
    get_settings.cache_clear()


# --- Invariant 1: API precedence on the real app ---------------------------


@pytest.mark.asyncio
async def test_health_still_served() -> None:
    transport = ASGITransport(app=real_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_api_platforms_still_served() -> None:
    transport = ASGITransport(app=real_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/platforms")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --- Invariants 2 + 3: SPA fallback vs API 404 -----------------------------


@pytest.mark.asyncio
async def test_unknown_path_returns_index_html(_dist_settings: Path) -> None:
    app = _app_with_dist(_dist_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/devices/some-deep-link")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "id=root" in resp.text


@pytest.mark.asyncio
async def test_concrete_static_file_served(_dist_settings: Path) -> None:
    app = _app_with_dist(_dist_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.text == "icon"


@pytest.mark.asyncio
async def test_api_miss_stays_404_not_index(_dist_settings: Path) -> None:
    app = _app_with_dist(_dist_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/nonexistent")
    assert resp.status_code == 404
    # Must NOT be the HTML shell.
    assert "id=root" not in resp.text


@pytest.mark.asyncio
async def test_root_serves_index(_dist_settings: Path) -> None:
    app = _app_with_dist(_dist_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "id=root" in resp.text


# --- Invariant 4: missing dist => app boots, API works ---------------------


@pytest.mark.asyncio
async def test_missing_dist_boots_without_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("NB_FRONTEND_DIST", str(missing))
    get_settings.cache_clear()
    try:
        app = _app_with_dist(missing)  # mount_spa no-ops (warns)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/health")
            spa = await client.get("/some/spa/route")
        assert health.status_code == 200
        # No SPA mounted => the catch-all route was never registered, so an
        # unknown path is a plain 404 (API still fully functional).
        assert spa.status_code == 404
    finally:
        get_settings.cache_clear()
