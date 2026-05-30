#!/usr/bin/env python3
"""Idempotent database seed for Northbound.

Brings a fresh deployment to a loginable state: ensures the schema exists, then
creates the baseline users (``admin`` + ``alice``). Re-running is safe — existing
users and devices are detected and skipped, never duplicated or overwritten.

Schema strategy
---------------
By default the schema is created via Alembic (``alembic upgrade head``) so the
seeded DB is migration-identical to production. Pass ``--create-all`` to use
``Base.metadata.create_all`` instead (fast, dev-only, no migration parity).

Passwords
---------
Passwords come from the environment:

* ``NB_SEED_ADMIN_PASSWORD`` for ``admin``
* ``NB_SEED_ALICE_PASSWORD`` for ``alice``

When unset, a random password is generated and **printed once, loudly** — only
acceptable for development. Passwords are always stored as a bcrypt hash via
``auth.password.hash_password``; plaintext is never persisted.

Sample devices
--------------
``--with-sample-devices`` seeds 1-2 ``mock``-platform devices so the UI shows
data without real hardware. Their credentials are encrypted at rest via the
CredVault, never stored in plaintext.

Usage
-----
    python seed.py                          # users only, alembic schema
    python seed.py --with-sample-devices    # + two mock devices
    python seed.py --create-all             # metadata.create_all (dev)
    python seed.py --help
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
import subprocess
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Importing the package registers every model on Base.metadata.
import northbound.models  # noqa: F401
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.db import Base, async_session_factory, engine
from northbound.models.device import Device
from northbound.models.enums import DeviceRole, Environment, UserRole
from northbound.models.user import User
from northbound.schemas.driver import Credentials
from northbound.services.credvault import FernetCredVault, serialize_credentials

logger = logging.getLogger("northbound.seed")

_ENV_PASSWORD_BY_USERNAME: dict[str, str] = {
    "admin": "NB_SEED_ADMIN_PASSWORD",
    "alice": "NB_SEED_ALICE_PASSWORD",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


async def ensure_schema(*, use_alembic: bool) -> None:
    """Ensure all tables exist (idempotent)."""
    if use_alembic:
        logger.info("ensuring schema via 'alembic upgrade head'")
        # Run the migration as a subprocess so alembic owns its own event loop
        # (its env.py calls asyncio.run, which cannot nest in our loop).
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("alembic upgrade failed:\n%s", result.stderr.strip())
            raise RuntimeError("alembic upgrade head failed; see log above")
        logger.info("schema is at head")
    else:
        logger.info("ensuring schema via Base.metadata.create_all (dev mode)")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def _resolve_password(username: str) -> str:
    """Return the configured password, or mint+print a random dev one.

    Reads the env var for the username; if unset, generates a URL-safe random
    password and prints it once to stderr (LOUD). Never returns plaintext via
    logging at INFO — the print is the single, deliberate disclosure.
    """
    import os

    env_var = _ENV_PASSWORD_BY_USERNAME[username]
    configured = os.environ.get(env_var)
    if configured:
        return configured

    generated = secrets.token_urlsafe(16)
    banner = "=" * 72
    print(
        f"\n{banner}\n"
        f"  NO {env_var} SET — generated a RANDOM password for {username!r}:\n\n"
        f"      {generated}\n\n"
        f"  This is printed ONCE and is NOT stored in plaintext. Save it now.\n"
        f"  Set {env_var} for reproducible / production seeding.\n"
        f"{banner}\n",
        file=sys.stderr,
        flush=True,
    )
    return generated


async def _ensure_user(
    session: AsyncSession,
    *,
    username: str,
    role: UserRole,
    email: str | None,
) -> bool:
    """Create the user if absent. Return True if created, False if skipped."""
    existing = await session.scalar(select(User).where(User.username == username))
    if existing is not None:
        logger.info("user %r already exists (role=%s) — skipping", username, existing.role.value)
        return False

    password = _resolve_password(username)
    session.add(
        User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            email=email,
        )
    )
    logger.info("created user %r (role=%s)", username, role.value)
    return True


async def seed_users(session: AsyncSession) -> int:
    """Ensure baseline users exist. Return count created."""
    created = 0
    created += await _ensure_user(
        session, username="admin", role=UserRole.ADMIN, email="admin@northbound.local"
    )
    created += await _ensure_user(
        session, username="alice", role=UserRole.REQUESTER, email="alice@northbound.local"
    )
    return created


# ---------------------------------------------------------------------------
# Sample devices (optional)
# ---------------------------------------------------------------------------

# Static, mock-platform sample inventory. Credentials are placeholders the
# MockDriver ignores; they are still encrypted at rest so the seed exercises
# the same code path a real onboarding would.
_SAMPLE_DEVICES: tuple[dict[str, object], ...] = (
    {
        "name": "lab-leaf-01",
        "environment": Environment.LAB,
        "role": DeviceRole.LEAF,
        "mgmt_ip": "10.0.0.11",
    },
    {
        "name": "lab-spine-01",
        "environment": Environment.DC,
        "role": DeviceRole.SPINE,
        "mgmt_ip": "10.0.0.21",
    },
)


async def _ensure_device(session: AsyncSession, spec: dict[str, object]) -> bool:
    """Create a mock-platform device if absent. Return True if created."""
    name = spec["name"]
    assert isinstance(name, str)
    existing = await session.scalar(select(Device).where(Device.name == name))
    if existing is not None:
        logger.info("device %r already exists — skipping", name)
        return False

    vault = FernetCredVault.from_settings()
    creds = Credentials(username="seed", password=secrets.token_urlsafe(12))
    session.add(
        Device(
            name=name,
            environment=spec["environment"],
            platform="mock",
            role=spec["role"],
            mgmt_ip=spec["mgmt_ip"],
            ssh_user="seed",
            prefer_native_api=True,
            encrypted_credentials=serialize_credentials(creds, vault),
        )
    )
    logger.info("created sample device %r (platform=mock)", name)
    return True


async def seed_sample_devices(session: AsyncSession) -> int:
    """Ensure sample mock devices exist. Return count created."""
    created = 0
    for spec in _SAMPLE_DEVICES:
        created += await _ensure_device(session, spec)
    return created


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def run(*, use_alembic: bool, with_sample_devices: bool) -> None:
    """Run the full idempotent seed."""
    settings = get_settings()
    logger.info("seeding (environment=%s, db_url=%s)", settings.environment, settings.db_url)

    await ensure_schema(use_alembic=use_alembic)

    async with async_session_factory() as session:
        users_created = await seed_users(session)
        devices_created = 0
        if with_sample_devices:
            devices_created = await seed_sample_devices(session)
        await session.commit()

    logger.info(
        "seed complete: %d user(s) created, %d sample device(s) created",
        users_created,
        devices_created,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Idempotent Northbound database seed (users + optional sample devices).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--with-sample-devices",
        action="store_true",
        help="Also seed 1-2 mock-platform devices (encrypted creds) so the UI shows data.",
    )
    parser.add_argument(
        "--create-all",
        action="store_true",
        help="Create schema via Base.metadata.create_all instead of 'alembic upgrade head' "
        "(dev only; loses migration parity).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    args = _parse_args(argv)
    asyncio.run(
        run(
            use_alembic=not args.create_all,
            with_sample_devices=args.with_sample_devices,
        )
    )


if __name__ == "__main__":
    main()
