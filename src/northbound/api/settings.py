"""Settings router — admin-tunable runtime knobs (no redeploy).

Currently exposes the write-endpoint rate limit. Reads come from the in-memory
cache (instant); writes validate the value, persist it, and update the cache so
the next request sees the new limit. Admin-only on both verbs.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.deps import require_admin
from northbound.db import get_session
from northbound.models.user import User
from northbound.schemas.settings import SettingsOut, SettingsPatch
from northbound.services import runtime_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _current() -> SettingsOut:
    return SettingsOut(write_rate_limit=runtime_settings.current_write_rate_limit())


@router.get("", response_model=SettingsOut)
async def get_runtime_settings(
    _admin: Annotated[User, Depends(require_admin)],
) -> SettingsOut:
    """Return the current admin-tunable settings."""
    return _current()


@router.patch("", response_model=SettingsOut)
async def update_runtime_settings(
    body: SettingsPatch,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SettingsOut:
    """Update runtime settings (admin). 422 on an invalid rate-limit string."""
    if body.write_rate_limit is not None:
        try:
            runtime_settings.validate_rate_limit(body.write_rate_limit)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        await runtime_settings.set_value(
            session,
            runtime_settings.WRITE_RATE_LIMIT_KEY,
            body.write_rate_limit,
            updated_by=admin.id,
        )
    return _current()
