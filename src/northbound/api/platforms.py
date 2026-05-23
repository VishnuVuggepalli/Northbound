"""GET /api/platforms — driver registry, surfaced for the onboarding wizard."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from northbound.drivers.registry import all_platforms
from northbound.schemas.driver import DriverCapabilities

router = APIRouter(prefix="/api", tags=["platforms"])


class PlatformInfo(BaseModel):
    platform_id: str
    display_name: str
    capabilities: DriverCapabilities


@router.get("/platforms", response_model=list[PlatformInfo])
async def list_platforms() -> list[PlatformInfo]:
    return [
        PlatformInfo(
            platform_id=cls.platform_id,
            display_name=cls.display_name,
            capabilities=cls.capabilities,
        )
        for cls in all_platforms().values()
    ]
