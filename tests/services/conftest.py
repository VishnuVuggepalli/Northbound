"""Fixtures for the services layer tests.

Seeds an admin + requester user and a writable ``mock``-platform device with
encrypted credentials, and resets the module-level port_state / config caches
between tests so cache state never leaks across cases.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("NB_SECRET_KEY", "unit-test-secret-key")
os.environ.setdefault("NB_MASTER_KEY", "wDPYj3kZ3qbY8m0v6m2nQ1rJf7xq9o5xS3uVc8nH0cE=")

import northbound.drivers.mock  # noqa: F401  (registers the "mock" platform)
from northbound.auth.password import hash_password
from northbound.config import get_settings
from northbound.models.device import Device
from northbound.models.enums import DeviceRole, UserRole
from northbound.models.user import User
from northbound.schemas.driver import Credentials
from northbound.services import port_state
from northbound.services.credvault import FernetCredVault, serialize_credentials

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    """Clear the in-mem port-state cache before and after each test."""
    port_state._cache.clear()
    yield
    port_state._cache.clear()


@pytest_asyncio.fixture
async def mock_device(db_session: AsyncSession) -> AsyncIterator[Device]:
    """A writable mock-platform device with encrypted credentials stored."""
    vault = FernetCredVault.from_settings()
    device = Device(
        name="lab-mock-1",
        environment="lab",
        platform="mock",
        role=DeviceRole.LEAF,
        mgmt_ip="10.0.0.5",
        ssh_user="admin",
        prefer_native_api=True,
        encrypted_credentials=serialize_credentials(
            Credentials(username="admin", password="switch-pw"), vault
        ),
    )
    db_session.add(device)
    await db_session.flush()
    yield device


@pytest_asyncio.fixture
async def users(db_session: AsyncSession) -> AsyncIterator[tuple[User, User]]:
    """An (admin, requester) pair."""
    admin = User(username="admin", password_hash=hash_password("a"), role=UserRole.ADMIN)
    alice = User(username="alice", password_hash=hash_password("b"), role=UserRole.REQUESTER)
    db_session.add_all([admin, alice])
    await db_session.flush()
    yield admin, alice
