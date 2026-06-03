import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Importing a driver module triggers @register at import time.
# Order is alphabetical to keep /api/platforms output stable.
import northbound.drivers.arista
import northbound.drivers.cisco
import northbound.drivers.mikrotik
import northbound.drivers.mikrotik_swos
import northbound.drivers.mock
import northbound.drivers.pica8  # noqa: F401  (registers)
from northbound.api import (
    audit,
    auth,
    devices,
    platforms,
    ports,
    requests,
    sites,
    users,
)
from northbound.api import settings as settings_api
from northbound.api.limiter import limiter
from northbound.api.static_spa import mount_spa
from northbound.api.versioning import ApiVersionMiddleware
from northbound.config import get_settings
from northbound.db import async_session_factory
from northbound.services import runtime_settings
from northbound.services.scheduler import build_scheduler
from northbound.services.sites import ensure_default_sites

logger = logging.getLogger("northbound.main")


class HealthResponse(BaseModel):
    status: str


def _rate_limit_handler(request: Request, exc: Exception) -> Response:
    """Starlette-compatible adapter around slowapi's 429 handler.

    Starlette types handlers against the base ``Exception``; slowapi's handler
    is narrowed to ``RateLimitExceeded``. We narrow back here so the signature
    matches without suppressing the type check.
    """
    assert isinstance(exc, RateLimitExceeded)  # only registered for this type
    return _rate_limit_exceeded_handler(request, exc)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the in-process scheduler on startup; stop it on shutdown.

    Gated on ``settings.enable_scheduler`` (forced ``False`` under tests) so the
    test suite never spawns real APScheduler timers — which would otherwise keep
    the event loop alive and hang collection. In production the four background
    jobs (reachability poll, nightly backup, audit verify, reconciler) run here.
    """
    settings = get_settings()

    # Seed the default Lab/DC sites so a fresh DB has a usable catalog. Idempotent
    # and resilient: a missing ``sites`` table (migration not yet run) only logs.
    try:
        async with async_session_factory() as session, session.begin():
            await ensure_default_sites(session)
    except Exception:
        logger.warning("default-site seed skipped (sites table missing?)", exc_info=True)

    # Seed the runtime-settings cache (e.g. admin-tuned write rate limit) from the
    # DB. Resilient: a missing table (migration not yet run) only logs; reads fall
    # back to the env default until then.
    try:
        async with async_session_factory() as session:
            await runtime_settings.load_cache(session)
    except Exception:
        logger.warning("runtime-settings cache seed skipped (table missing?)", exc_info=True)

    scheduler: AsyncIOScheduler | None = None
    if settings.enable_scheduler:
        scheduler = build_scheduler(settings)
        scheduler.start()
        logger.info("scheduler started with %d job(s)", len(scheduler.get_jobs()))
    else:
        logger.info("scheduler disabled (enable_scheduler=False); no background jobs")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("scheduler shut down")


app = FastAPI(title="Northbound", version="0.1.0", lifespan=lifespan)

# API versioning: 406 a request that pins an unsupported version via Accept, and
# stamp X-API-Version on every response. Added first so it wraps outermost.
app.add_middleware(ApiVersionMiddleware)

# Reverse-proxy support: only honour X-Forwarded-* (so the rate limiter and
# logs see the real client IP, not the proxy's) when explicitly enabled and
# from trusted proxy hops. Default off — forwarded headers are client-spoofable
# unless terminated by a controlled proxy. See Settings.trust_proxy_headers.
_settings = get_settings()
if _settings.trust_proxy_headers:
    _trusted = [h.strip() for h in _settings.trusted_proxies.split(",") if h.strip()]
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted or "127.0.0.1")

# Wire the slowapi limiter: state + the 429 exception handler.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.include_router(platforms.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(sites.router)
app.include_router(ports.router)
app.include_router(requests.router)
app.include_router(audit.router)
app.include_router(settings_api.router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


# Static SPA last: it registers a catch-all that must not shadow the API.
# No-ops (with a warning) when the frontend has not been built.
mount_spa(app)
