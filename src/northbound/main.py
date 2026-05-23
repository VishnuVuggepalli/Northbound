from fastapi import FastAPI
from pydantic import BaseModel

# Importing the mock driver registers it via the @register decorator.
# Future drivers go through the same pattern.
import northbound.drivers.mock  # noqa: F401
from northbound.api import platforms


class HealthResponse(BaseModel):
    status: str


app = FastAPI(title="Northbound", version="0.1.0")
app.include_router(platforms.router)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
