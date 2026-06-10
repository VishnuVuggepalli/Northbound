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
from typing import Any, Literal

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


def _read_secret_file(path: str | None, env_name: str) -> str | None:
    """Read a secret from ``path`` (Docker/K8s/systemd secrets convention).

    Returns ``None`` when ``path`` is unset (caller falls back to the inline
    value / dev mint). A configured-but-unreadable or empty file raises — a
    misconfigured secret source must fail loudly, never degrade to ephemeral.
    Trailing whitespace/newline (common in secret files) is stripped.
    """
    if not path:
        return None
    file = Path(path)
    try:
        value = file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"{env_name}={path!r} could not be read: {exc}") from exc
    if not value:
        raise ValueError(f"{env_name}={path!r} is empty")
    return value


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
    # Optional: read the master key from a FILE instead of an inline env value
    # (Docker/K8s/systemd secrets convention — keeps the secret off the command
    # line and out of `ps`/process env). Inline NB_MASTER_KEY wins if both set.
    master_key_file: str | None = Field(default=None)

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
    # Optional: read the JWT secret from a FILE (same secrets convention as
    # master_key_file). Inline NB_SECRET_KEY wins if both are set.
    secret_key_file: str | None = Field(default=None)
    # Allowlist of strong HMAC algorithms only — a free-form string would let a
    # misconfigured NB_JWT_ALGORITHM (e.g. "none") silently weaken token signing.
    # (jwt_expiry_minutes was removed: a dead legacy field that LOOKED like the
    # token-lifetime knob but was read by nothing — access_token_minutes is.)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = Field(default="HS256")

    # Cookie-based session (hardened): short-lived access token + long-lived
    # refresh token, both in httpOnly cookies. Access is sent on every request;
    # refresh is used only at /api/auth/refresh to rotate.
    access_token_minutes: int = Field(default=30, ge=1)
    refresh_token_days: int = Field(default=14, ge=1)
    # Mark auth cookies Secure (HTTPS-only) outside development. Overridable for
    # an HTTPS dev box; default tracks the environment so http://localhost works.
    cookie_secure: bool | None = Field(default=None)

    @property
    def auth_cookie_secure(self) -> bool:
        """Whether to set the Secure flag on auth cookies."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment != "development"

    # SSH/NETCONF host-key verification for device connections. Default OFF
    # (lab reality: device keys aren't pre-distributed), which leaves the
    # control channel MITM-able — production should distribute a known_hosts
    # file and enable strict mode. Outside development a loud warning is logged
    # at startup while this is off. Cannot default-strict: it would brick every
    # existing deployment that has never collected host keys.
    ssh_strict_host_keys: bool = Field(default=False)
    ssh_known_hosts_path: str | None = Field(default=None)  # required when strict

    # Extra Origins allowed to make state-changing requests, beyond same-origin
    # (e.g. a separately-hosted SPA: NB_ALLOWED_ORIGINS='["https://nb.corp"]').
    # Same-origin (Origin matching the request Host) is always allowed; this
    # never needs setting for the default single-container deployment.
    allowed_origins: list[str] = Field(default_factory=list)

    # Open self-registration: when true, anyone who can reach the API can POST
    # /api/auth/register to create a REQUESTER account (never admin). Default
    # OFF (secure-by-default): an internet-reachable deployment must not accept
    # anonymous account creation unless the operator explicitly opts in with
    # NB_ALLOW_OPEN_REGISTRATION=1.
    allow_open_registration: bool = Field(default=False)

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

    # --- Multi-worker / horizontal scaling ---
    # Shared rate-limit storage backend, e.g. "redis://redis:6379/0". When unset
    # (the single-worker default) slowapi uses per-process in-memory counters,
    # which are NOT shared across workers, so running N workers would allow about
    # N times the configured limit. Set this to a Redis (or memcached) URI
    # whenever more than one worker runs. See ``api.limiter`` and the [redis] extra.
    ratelimit_storage_uri: str | None = Field(default=None)
    # Leader-election retry cadence (seconds): exactly one worker runs the
    # scheduler, elected via a Postgres advisory lock. A non-leader re-attempts
    # acquisition this often so it can take over if the leader process dies.
    # Ignored on SQLite (single process is always the leader). See
    # ``services.scheduler_lease``.
    scheduler_lock_retry_seconds: int = Field(default=15, ge=1)
    # How often each worker reloads admin-tuned runtime settings (e.g. the write
    # rate limit) from the DB, so a change made on one worker propagates to all
    # of them within this window. Only runs when ``enable_scheduler`` is True.
    runtime_settings_refresh_seconds: int = Field(default=30, ge=1)

    # --- Static frontend (principal-engineering D9: StaticFiles mount on /) ---
    # Directory of the built Vite SPA (``frontend/dist``). Resolved relative to
    # the repo root when not absolute. If the directory is missing the mount is
    # skipped with a warning — the API still serves. Override via NB_FRONTEND_DIST.
    frontend_dist: str = Field(default="frontend/dist")

    @model_validator(mode="after")
    def _load_file_secrets(self) -> Settings:
        """Resolve ``*_key`` from a ``*_key_file`` path when no inline value is set.

        Standard Docker/K8s/systemd secrets convention: the secret lives in a
        file (e.g. ``/run/secrets/nb_master_key``) instead of an inline env var,
        keeping it off the command line and out of the process environment. The
        inline value wins if both are present. A configured-but-unreadable/empty
        file is a hard error (fail fast at a security boundary — never silently
        fall back to a dev-ephemeral key).
        """
        self.master_key = self.master_key or _read_secret_file(
            self.master_key_file, "NB_MASTER_KEY_FILE"
        )
        self.secret_key = self.secret_key or _read_secret_file(
            self.secret_key_file, "NB_SECRET_KEY_FILE"
        )
        return self

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
