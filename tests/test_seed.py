"""Seed script tests — idempotency, roles, hashing, encrypted sample creds.

These exercise the seed's unit functions against the in-memory ``db_session``
fixture (root conftest), so they never touch the module-level engine or the
filesystem. The functions own the create-if-absent logic; ``run()`` just wires
schema + commit around them.
"""

from __future__ import annotations

import pytest
import seed as seed_module
from sqlalchemy import func, select

from northbound.auth.password import verify_password
from northbound.models.device import Device
from northbound.models.enums import UserRole
from northbound.models.user import User
from northbound.services.credvault import FernetCredVault, deserialize_credentials


@pytest.fixture(autouse=True)
def _seed_passwords(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic passwords so the random-generate branch never fires."""
    monkeypatch.setenv("NB_SEED_ADMIN_PASSWORD", "admin-pw-123")
    monkeypatch.setenv("NB_SEED_ALICE_PASSWORD", "alice-pw-456")


@pytest.fixture
def _dev_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force a development environment so CredVault mints an ephemeral key."""
    monkeypatch.setenv("NB_ENVIRONMENT", "development")
    monkeypatch.delenv("NB_MASTER_KEY", raising=False)
    seed_module.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_seed_users_creates_admin_and_alice(db_session) -> None:
    created = await seed_module.seed_users(db_session)
    await db_session.commit()

    assert created == 2
    admin = await db_session.scalar(select(User).where(User.username == "admin"))
    alice = await db_session.scalar(select(User).where(User.username == "alice"))
    assert admin is not None and admin.role is UserRole.ADMIN
    assert alice is not None and alice.role is UserRole.REQUESTER


@pytest.mark.asyncio
async def test_seed_passwords_are_hashed_not_plaintext(db_session) -> None:
    await seed_module.seed_users(db_session)
    await db_session.commit()

    admin = await db_session.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    # Stored value is a bcrypt hash, not the plaintext.
    assert admin.password_hash != "admin-pw-123"
    assert admin.password_hash.startswith("$2")
    assert verify_password("admin-pw-123", admin.password_hash)


@pytest.mark.asyncio
async def test_seed_users_is_idempotent(db_session) -> None:
    first = await seed_module.seed_users(db_session)
    await db_session.commit()
    second = await seed_module.seed_users(db_session)
    await db_session.commit()

    assert first == 2
    assert second == 0  # second run skips both — nothing re-created

    total = await db_session.scalar(select(func.count()).select_from(User))
    assert total == 2
    # Exactly one of each username — no duplicates.
    for username in ("admin", "alice"):
        count = await db_session.scalar(
            select(func.count()).select_from(User).where(User.username == username)
        )
        assert count == 1


@pytest.mark.asyncio
async def test_seed_sample_devices_idempotent_and_encrypted(db_session, _dev_vault: None) -> None:
    created = await seed_module.seed_sample_devices(db_session)
    await db_session.commit()
    assert created == len(seed_module._SAMPLE_DEVICES)

    second = await seed_module.seed_sample_devices(db_session)
    await db_session.commit()
    assert second == 0  # idempotent

    devices = (await db_session.scalars(select(Device))).all()
    assert len(devices) == len(seed_module._SAMPLE_DEVICES)
    for device in devices:
        assert device.platform == "mock"
        # Credentials are an opaque ciphertext blob, never plaintext.
        assert device.encrypted_credentials is not None
        assert b"seed" not in device.encrypted_credentials  # username not in plaintext


@pytest.mark.asyncio
async def test_sample_device_creds_round_trip(db_session, _dev_vault: None) -> None:
    """The encrypted blob decrypts back to usable Credentials (same key)."""
    # Pin one vault instance so encrypt + decrypt share a key (ephemeral dev key
    # is otherwise regenerated per FernetCredVault.from_settings call).
    vault = FernetCredVault.from_settings()
    import northbound.services.credvault as cv

    original_from_settings = cv.FernetCredVault.from_settings
    cv.FernetCredVault.from_settings = classmethod(lambda cls, settings=None: vault)  # type: ignore[assignment]
    try:
        await seed_module.seed_sample_devices(db_session)
        await db_session.commit()
    finally:
        cv.FernetCredVault.from_settings = original_from_settings  # type: ignore[assignment]

    device = await db_session.scalar(select(Device))
    assert device is not None and device.encrypted_credentials is not None
    creds = deserialize_credentials(device.encrypted_credentials, vault)
    assert creds.username == "seed"
    assert creds.password is not None
