import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
    events,
    platforms,
    ports,
    requests,
    sites,
    users,
)
from northbound.api import settings as settings_api
from northbound.api.limiter import limiter
from northbound.api.security_headers import SecurityHeadersMiddleware
from northbound.api.static_spa import mount_spa
from northbound.api.versioning import ApiVersionMiddleware
from northbound.config import get_settings
from northbound.db import async_session_factory, engine
from northbound.services import runtime_settings
from northbound.services.scheduler_lease import SchedulerLease
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
    """Start background tasks on startup; stop them on shutdown.

    Two background tasks run only when ``settings.enable_scheduler`` is True
    (forced ``False`` under tests so the suite never spawns real timers — which
    would keep the event loop alive and hang collection):

    * A :class:`SchedulerLease` that elects a single leader (Postgres advisory
      lock) and runs the four jobs (reachability poll, nightly backup, audit
      verify, reconciler) in exactly ONE worker — never N times under
      multi-worker. On SQLite the lone process is always the leader.
    * A runtime-settings refresh loop in EVERY worker, so an admin change made
      on one worker (e.g. the write rate limit) converges to the others.
    """
    settings = get_settings()

    # Loud, repeated-at-every-boot warning: with host-key verification off, the
    # SSH/NETCONF control channel to devices is MITM-able (device credentials
    # could be harvested by an on-path attacker). Acceptable in a lab; a
    # production deployment should distribute known_hosts and set
    # NB_SSH_STRICT_HOST_KEYS=1 (+ NB_SSH_KNOWN_HOSTS_PATH).
    if settings.environment != "development" and not settings.ssh_strict_host_keys:
        logger.warning(
            "SSH/NETCONF host-key verification is DISABLED outside development — "
            "device connections are MITM-able. Set NB_SSH_STRICT_HOST_KEYS=1 "
            "with NB_SSH_KNOWN_HOSTS_PATH for production."
        )

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

    lease: SchedulerLease | None = None
    refresh_stop: asyncio.Event | None = None
    refresh_task: asyncio.Task[None] | None = None
    if settings.enable_scheduler:
        lease = SchedulerLease(engine, settings)
        await lease.start()
        refresh_stop = asyncio.Event()
        refresh_task = asyncio.create_task(
            runtime_settings.refresh_loop(
                async_session_factory,
                settings.runtime_settings_refresh_seconds,
                refresh_stop,
            ),
            name="runtime-settings-refresh",
        )
    else:
        logger.info("background tasks disabled (enable_scheduler=False)")
    try:
        yield
    finally:
        if refresh_stop is not None:
            refresh_stop.set()
        if refresh_task is not None:
            await refresh_task
        if lease is not None:
            await lease.stop()
            logger.info("scheduler lease stopped")


app = FastAPI(title="Northbound", version="0.1.0", lifespan=lifespan)

# API versioning: 406 a request that pins an unsupported version via Accept, and
# stamp X-API-Version on every response. Added first so it wraps outermost.
app.add_middleware(ApiVersionMiddleware)

# Security headers (X-Frame-Options / nosniff / Referrer-Policy / CSP / HSTS) on
# every response + cross-origin write rejection (the SameSite=Lax CSRF gap).
app.add_middleware(SecurityHeadersMiddleware)

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
app.include_router(events.router)
app.include_router(settings_api.router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


# Static SPA last: it registers a catch-all that must not shadow the API.
# No-ops (with a warning) when the frontend has not been built.
mount_spa(app)
