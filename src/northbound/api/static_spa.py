"""Static SPA serving for the built Vite frontend (principal-engineering D9).

The built ``frontend/dist`` is served from ``/``: hashed assets straight off
disk, and any unknown non-API path falls back to ``index.html`` so client-side
routing and deep-links work. This must be mounted **after** all ``/api/*``
routers and ``/health`` so the API always takes precedence; ``/api/*`` misses
stay 404 (never the SPA shell).

If the dist directory is missing, ``mount_spa`` logs a warning and does nothing
— the API keeps working, the app still boots. This keeps a backend-only
deployment (or a dev box that hasn't run ``npm run build``) functional.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from northbound.config import get_settings

logger = logging.getLogger("northbound.static")

# Path prefixes that the SPA fallback must never shadow. A miss under these
# returns a real 404 (JSON), not the HTML shell.
_API_PREFIXES: tuple[str, ...] = ("/api", "/health", "/docs", "/redoc", "/openapi.json")


def _repo_root() -> Path:
    """Repo root = three parents up from this file (src/northbound/api/...)."""
    return Path(__file__).resolve().parents[3]


def resolve_dist_dir() -> Path:
    """Resolve the configured dist directory to an absolute path.

    A relative ``frontend_dist`` is anchored at the repo root so the server
    finds the build regardless of the process working directory.
    """
    configured = Path(get_settings().frontend_dist)
    if configured.is_absolute():
        return configured
    return _repo_root() / configured


def mount_spa(app: FastAPI) -> None:
    """Mount the built SPA on ``/`` with an index.html fallback.

    No-ops with a warning if the dist directory (or its index.html) is absent.
    Registers the catch-all route last so it cannot intercept API paths.
    """
    dist_dir = resolve_dist_dir()
    index_file = dist_dir / "index.html"
    if not index_file.is_file():
        logger.warning(
            "frontend dist not found at %s — skipping static mount (API still served). "
            "Run 'make frontend-build' to build the SPA.",
            dist_dir,
        )
        return

    # Hashed asset bundles (JS/CSS) live under /assets — serve them directly.
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request) -> FileResponse:
        """Serve a real file if it exists, else the SPA shell.

        ``/api/*`` (and other reserved prefixes) that reach here are genuine
        misses — the routers already ran — so we 404 instead of masking them
        with HTML.
        """
        path = "/" + full_path
        if any(path == p or path.startswith(p + "/") for p in _API_PREFIXES):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

        # Serve a concrete static file (favicon, manifest, etc.) when present;
        # otherwise hand back index.html for client-side routing.
        candidate = (dist_dir / full_path).resolve()
        if full_path and candidate.is_file() and dist_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index_file)

    logger.info("mounted SPA from %s", dist_dir)
