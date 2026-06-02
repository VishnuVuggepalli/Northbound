"""Application settings.

Layered precedence (highest first): environment variables (``NB_`` prefix)
→ ``northbound.toml`` in the working directory → field defaults. Settings are
read once and cached as a process-wide singleton via :func:`get_settings`.
"""

from __future__ import annotations

import logging
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_CONFIG_FILE = Path("northbound.toml")

logger = logging.getLogger("northbound.config")

# CON-3 invariant: the reconciler's stale-apply cutoff must comfortably exceed
# the worst realistic apply wall time, or a genuinely-slow live apply (no
# intervening transition event during backup/render/apply_change) is wrongly
# killed as "interrupted", and the live coroutine then hits an illegal
# applying→awaiting_confirm transition on a now-FAILED row. The longest leg is
# the commit-confirm window; require the cutoff to be at least this many times it.
_APPLY_STALE_MIN_MULTIPLE = 3


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

    # Reverse-proxy trust. When True, X-Forwarded-For/Proto headers are honoured
    # so the rate limiter keys on the real client IP rather than the proxy's.
    # Default False: never blindly trust forwarded headers (they are
    # client-spoofable when not behind a controlled proxy). ``trusted_proxies``
    # lists the proxy hops allowed to set them (default: loopback only).
    trust_proxy_headers: bool = Field(default=False)
    trusted_proxies: str = Field(default="127.0.0.1,::1")

    # JWT signing secret (env NB_SECRET_KEY). Required outside dev; in dev an
    # ephemeral key is minted with a warning (mirrors the master-key policy).
    secret_key: str | None = Field(default=None)
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiry_minutes: int = Field(default=480)

    # Open self-registration: when true, anyone can POST /api/auth/register to
    # create a REQUESTER account (never admin). Kill-switch for deployments that
    # require admin-provisioned accounts only.
    allow_open_registration: bool = Field(default=True)

    # Commit-confirm window (seconds) for platforms with native commit-confirm
    # (Arista session timer, Pica8 confirmed-commit). The apply flow passes this
    # to ``driver.apply_change``; the reconciler (next wave) honours the deadline.
    commit_confirm_seconds: int = Field(default=60, ge=1)

    # Live port-state cache TTL (seconds). principal-engineering D2: 30s.
    port_state_ttl_seconds: float = Field(default=30.0, gt=0)
    # Max distinct devices held in the in-mem port-state cache.
    port_state_cache_capacity: int = Field(default=512, ge=1)

    # --- Background jobs (APScheduler) — principal-engineering "polling jobs" ---
    # Reachability poll cadence (seconds). D2 reachability TTL = 60s.
    poll_interval_seconds: int = Field(default=60, ge=1)
    # Per-device reachability probe timeout (seconds); a slow/unreachable device
    # must not stall the whole poll batch.
    reachability_timeout_seconds: float = Field(default=5.0, gt=0)
    # Nightly config backup — cron (5-field: m h dom mon dow). 03:00 daily.
    nightly_backup_cron: str = Field(default="0 3 * * *")
    # Nightly audit-chain verify — cron. 03:30 daily (after the backup run).
    audit_verify_cron: str = Field(default="30 3 * * *")
    # Reconciler tick cadence (seconds). D4: every 10s.
    reconciler_interval_seconds: int = Field(default=10, ge=1)
    # An ``applying`` request whose latest event is older than this is treated as
    # crash-interrupted mid-apply (process died between APPLYING and the next
    # transition) and is failed for human review — never auto-retried.
    reconciler_apply_stale_seconds: int = Field(default=300, ge=1)
    # Master switch for the in-process scheduler. Forced False under tests so
    # the suite never spawns real timers (no hangs). See ``main.lifespan``.
    enable_scheduler: bool = Field(default=True)

    # --- Static frontend (principal-engineering D9: StaticFiles mount on /) ---
    # Directory of the built Vite SPA (``frontend/dist``). Resolved relative to
    # the repo root when not absolute. If the directory is missing the mount is
    # skipped with a warning — the API still serves. Override via NB_FRONTEND_DIST.
    frontend_dist: str = Field(default="frontend/dist")

    @model_validator(mode="after")
    def _clamp_apply_stale_seconds(self) -> Settings:
        """Enforce the CON-3 invariant: stale cutoff >> max apply wall time.

        Clamps ``reconciler_apply_stale_seconds`` up to
        ``_APPLY_STALE_MIN_MULTIPLE x commit_confirm_seconds`` when a config sets
        it too low, logging a warning. A slow-but-live apply within the window is
        therefore never mistaken for a crash. Returns ``self`` (validated copy).
        """
        floor = self.commit_confirm_seconds * _APPLY_STALE_MIN_MULTIPLE
        if self.reconciler_apply_stale_seconds < floor:
            logger.warning(
                "reconciler_apply_stale_seconds=%d is below the safe floor %d "
                "(%dx commit_confirm_seconds=%d); clamping up to protect slow "
                "live applies from being failed as interrupted (CON-3)",
                self.reconciler_apply_stale_seconds,
                floor,
                _APPLY_STALE_MIN_MULTIPLE,
                self.commit_confirm_seconds,
            )
            self.reconciler_apply_stale_seconds = floor
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton (env overrides TOML overrides defaults)."""
    return Settings(**_load_toml())
