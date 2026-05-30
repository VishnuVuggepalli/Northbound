from fastapi import FastAPI
from pydantic import BaseModel

# Importing a driver module triggers @register at import time.
# Order is alphabetical to keep /api/platforms output stable.
import northbound.drivers.arista
import northbound.drivers.cisco
import northbound.drivers.mock
import northbound.drivers.pica8  # noqa: F401  (registers)
from northbound.api import platforms


class HealthResponse(BaseModel):
    status: str


app = FastAPI(title="Northbound", version="0.1.0")
app.include_router(platforms.router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
