import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Importing a driver module triggers @register at import time.
# Order is alphabetical to keep /api/platforms output stable.
import northbound.drivers.arista
import northbound.drivers.cisco
import northbound.drivers.mock
import northbound.drivers.pica8  # noqa: F401  (registers)
from northbound.api import audit, auth, devices, platforms, ports, requests, users
from northbound.api.limiter import limiter
from northbound.api.static_spa import mount_spa
from northbound.config import get_settings
from northbound.services.scheduler import build_scheduler

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

# Wire the slowapi limiter: state + the 429 exception handler.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.include_router(platforms.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(ports.router)
app.include_router(requests.router)
app.include_router(audit.router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


# Static SPA last: it registers a catch-all that must not shadow the API.
# No-ops (with a warning) when the frontend has not been built.
mount_spa(app)
