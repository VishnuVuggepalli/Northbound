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
from northbound.api import auth, platforms, users
from northbound.api.limiter import limiter


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


app = FastAPI(title="Northbound", version="0.1.0")

# Wire the slowapi limiter: state + the 429 exception handler.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.include_router(platforms.router)
app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
