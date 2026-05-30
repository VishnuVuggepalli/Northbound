"""Application settings.

Layered precedence (highest first): environment variables (``NB_`` prefix)
→ ``northbound.toml`` in the working directory → field defaults. Settings are
read once and cached as a process-wide singleton via :func:`get_settings`.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_CONFIG_FILE = Path("northbound.toml")


def _load_toml() -> dict[str, Any]:
    """Read ``northbound.toml`` if present; empty mapping otherwise."""
    if not _CONFIG_FILE.is_file():
        return {}
    with _CONFIG_FILE.open("rb") as fh:
        return tomllib.load(fh)


class Settings(BaseSettings):
    """Runtime configuration.

    ``environment`` gates dev-only behaviour (e.g. ephemeral master key).
    ``master_key`` is the Fernet key for :class:`FernetCredVault`; it is a
    secret and is never logged.
    """

    model_config = SettingsConfigDict(
        env_prefix="NB_",
        env_file=None,
        extra="ignore",
    )

    environment: str = Field(default="development")

    # Async SQLAlchemy URL. Default = single-file SQLite via aiosqlite.
    db_url: str = Field(default="sqlite+aiosqlite:///./northbound.db")

    # Fernet master key (urlsafe-base64, 32 bytes). Required outside dev.
    master_key: str | None = Field(default=None)


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton (env overrides TOML overrides defaults)."""
    return Settings(**_load_toml())
