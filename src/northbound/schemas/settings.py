"""DTOs for the admin runtime-settings API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    """Current admin-tunable runtime settings."""

    write_rate_limit: str = Field(
        description="Write-endpoint rate limit as a slowapi/limits string, e.g. '30/minute'.",
    )


class SettingsPatch(BaseModel):
    """Partial update of runtime settings. Only set fields are applied."""

    write_rate_limit: str | None = Field(default=None, max_length=256)
