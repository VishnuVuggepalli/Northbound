"""Auth layer + /api/auth tests: password, JWT, login, throttle.

The FastAPI app is exercised via ``httpx.AsyncClient`` over ``ASGITransport``.
``get_session`` is overridden to bind handlers to the in-memory test session.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Pin the signing secret before settings are first read (deterministic JWTs).
os.environ["NB_SECRET_KEY"] = "unit-test-secret-key"

from northbound.api.limiter import limiter
from northbound.auth.jwt import (
    InvalidToken,
    create_access_token,
    decode_token,
)
from northbound.auth.password import hash_password, verify_password
from northbound.config import Settings, get_settings
from northbound.db import get_session
from northbound.main import app
from northbound.models.enums import UserRole
from northbound.models.user import User

get_settings.cache_clear()

_TEST_SETTINGS = Settings(environment="development", secret_key="unit-test-secret-key")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def seeded_session(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Session pre-loaded with an admin and a requester user."""
    db_session.add_all(
        [
            User(
                username="admin",
                password_hash=hash_password("admin-pw"),
                role=UserRole.ADMIN,
            ),
            User(
                username="alice",
                password_hash=hash_password("alice-pw"),
                role=UserRole.REQUESTER,
                email="alice@example.com",
            ),
        ]
    )
    await db_session.flush()
    yield db_session


@pytest_asyncio.fixture
async def client(seeded_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """AsyncClient bound to the app with ``get_session`` overridden, limiter reset."""

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield seeded_session

    app.dependency_overrides[get_session] = _override_get_session
    # Reset the in-memory rate-limit storage so tests don't leak attempts.
    limiter.reset()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        limiter.reset()


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cret")
    assert hashed != "s3cret"  # never stored in plaintext
    assert verify_password("s3cret", hashed) is True


def test_password_wrong_fails() -> None:
    hashed = hash_password("s3cret")
    assert verify_password("nope", hashed) is False


def test_password_verify_malformed_hash_returns_false() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def test_jwt_create_decode_roundtrip() -> None:
    token = create_access_token(sub="user-1", role=UserRole.ADMIN, settings=_TEST_SETTINGS)
    payload = decode_token(token, settings=_TEST_SETTINGS)
    assert payload.sub == "user-1"
    assert payload.role == UserRole.ADMIN


def test_jwt_expired_token_rejected() -> None:
    token = create_access_token(
        sub="user-1",
        role=UserRole.ADMIN,
        expiry=dt.timedelta(seconds=-1),
        settings=_TEST_SETTINGS,
    )
    with pytest.raises(InvalidToken):
        decode_token(token, settings=_TEST_SETTINGS)


def test_jwt_tampered_token_rejected() -> None:
    token = create_access_token(sub="user-1", role=UserRole.ADMIN, settings=_TEST_SETTINGS)
    tampered = token[:-3] + ("abc" if token[-3:] != "abc" else "xyz")
    with pytest.raises(InvalidToken):
        decode_token(tampered, settings=_TEST_SETTINGS)


def test_jwt_wrong_secret_rejected() -> None:
    token = create_access_token(sub="user-1", role=UserRole.ADMIN, settings=_TEST_SETTINGS)
    other = Settings(environment="development", secret_key="a-different-secret")
    with pytest.raises(InvalidToken):
        decode_token(token, settings=other)


# --------------------------------------------------------------------------- #
# POST /api/auth/login
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_login_valid_returns_token(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "admin-pw"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "admin"
    assert body["username"] == "admin"
    assert body["access_token"]


@pytest.mark.asyncio
async def test_login_bad_password_401_generic(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect username or password"


@pytest.mark.asyncio
async def test_login_unknown_user_same_message_no_enumeration(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401
    # Identical message to the bad-password case → no user enumeration.
    assert resp.json()["detail"] == "Incorrect username or password"


@pytest.mark.asyncio
async def test_login_unknown_user_runs_dummy_hash_verify(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-3: an unknown username still runs verify_password against the dummy
    hash, so the no-user and wrong-password branches take ~the same bcrypt time
    (timing-oracle closed). We assert the branch executes deterministically by
    spying on verify_password rather than measuring wall-clock time."""
    import northbound.api.auth as auth_module
    from northbound.auth.password import DUMMY_PASSWORD_HASH

    calls: list[tuple[str, str]] = []
    real_verify = auth_module.verify_password

    def _spy(plain: str, hashed: str) -> bool:
        calls.append((plain, hashed))
        return real_verify(plain, hashed)

    monkeypatch.setattr(auth_module, "verify_password", _spy)

    resp = await client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401
    # verify_password was called exactly once, against the constant dummy hash.
    assert calls == [("x", DUMMY_PASSWORD_HASH)]


@pytest.mark.asyncio
async def test_logout_returns_204(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 204


# --------------------------------------------------------------------------- #
# Login throttle (slowapi, IP-based: 5 / 5min)
# --------------------------------------------------------------------------- #
def test_login_limiter_registered_on_app() -> None:
    # The limiter must be wired into app.state for slowapi to enforce limits.
    assert app.state.limiter is limiter


@pytest.mark.asyncio
async def test_login_throttle_sixth_attempt_429(client: AsyncClient) -> None:
    """5 attempts allowed in the window; the 6th is rejected with 429."""
    last_status = None
    for _ in range(6):
        resp = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        last_status = resp.status_code
    assert last_status == 429


@pytest.mark.asyncio
async def test_login_throttle_keyed_per_username_same_ip(client: AsyncClient) -> None:
    """SEC-4: the limiter is keyed on (ip, username).

    Exhaust the budget for one username from this IP, then a *different*
    username from the same IP still has its own fresh budget (not collapsed into
    one IP-only bucket). This is what bounds password-spraying per-target while
    avoiding a single proxy IP locking everyone out.
    """
    # Burn through the 5/5min budget for "admin" → 6th is 429.
    for _ in range(6):
        burned = await client.post(
            "/api/auth/login", json={"username": "admin", "password": "wrong"}
        )
    assert burned.status_code == 429

    # Same IP, different username → independent bucket, first attempt allowed.
    other = await client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert other.status_code == 401  # bad password, NOT 429 (its own budget)


# --------------------------------------------------------------------------- #
# POST /api/auth/register (public self-registration → requester + auto-login)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_register_creates_requester_and_returns_token(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "hunter2pw", "email": "bob@example.com"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "requester"  # always requester, never admin
    assert body["username"] == "bob"
    assert body["access_token"]  # auto-login token issued
    # The issued token decodes to a requester.
    assert decode_token(body["access_token"], settings=_TEST_SETTINGS).role == UserRole.REQUESTER


@pytest.mark.asyncio
async def test_register_can_login_afterwards(client: AsyncClient) -> None:
    await client.post("/api/auth/register", json={"username": "carol", "password": "hunter2pw"})
    login = await client.post(
        "/api/auth/login", json={"username": "carol", "password": "hunter2pw"}
    )
    assert login.status_code == 200
    assert login.json()["role"] == "requester"


@pytest.mark.asyncio
async def test_register_ignores_role_escalation_attempt(client: AsyncClient) -> None:
    # An attacker passing role=admin must NOT get admin — the field is unknown to
    # RegisterRequest and is ignored; the account is still a requester.
    resp = await client.post(
        "/api/auth/register",
        json={"username": "mallory", "password": "hunter2pw", "role": "admin"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "requester"


@pytest.mark.asyncio
async def test_register_duplicate_username_409(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/register", json={"username": "admin", "password": "hunter2pw"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Username already exists"


@pytest.mark.asyncio
async def test_register_short_password_422(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/register", json={"username": "dave", "password": "short"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_disabled_returns_403(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import northbound.api.auth as auth_module

    disabled = Settings(
        environment="development",
        secret_key="unit-test-secret-key",
        allow_open_registration=False,
    )
    monkeypatch.setattr(auth_module, "get_settings", lambda: disabled)
    resp = await client.post(
        "/api/auth/register", json={"username": "eve", "password": "hunter2pw"}
    )
    assert resp.status_code == 403
