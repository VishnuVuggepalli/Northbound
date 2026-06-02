"""Auth router — login (throttled) and logout.

Login verifies credentials against the DB and returns a signed JWT. Errors are
deliberately generic (same message for unknown-user and wrong-password) to
avoid user enumeration. Logout is a stateless no-op for v1: JWTs are not
server-side revocable, so the client simply drops the token.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.limiter import (
    LOGIN_RATE_LIMIT,
    REGISTER_RATE_LIMIT,
    limiter,
    login_rate_key,
)
from northbound.auth.jwt import create_access_token
from northbound.auth.password import DUMMY_PASSWORD_HASH, hash_password, verify_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.models.enums import UserRole
from northbound.models.user import User
from northbound.schemas.auth import LoginRequest, LoginResponse, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Single generic message — never reveals whether the username exists.
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect username or password",
)


@router.post("/login", response_model=LoginResponse)
@limiter.limit(LOGIN_RATE_LIMIT, key_func=login_rate_key)
async def login(
    request: Request,
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    """Verify credentials and issue a JWT. 401 (generic) on any mismatch."""
    user = await session.scalar(select(User).where(User.username == body.username))

    # Equalize timing: when the user is missing we have no real hash, so we run
    # verify_password against a constant dummy bcrypt hash. This makes the
    # unknown-user and wrong-password paths take ~the same bcrypt time, closing
    # the timing oracle that would otherwise leak which usernames exist. The
    # error returned is identical in both branches (no enumeration via message).
    if user is None:
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        raise _INVALID_CREDENTIALS
    if not verify_password(body.password, user.password_hash):
        raise _INVALID_CREDENTIALS

    token = create_access_token(sub=user.id, role=user.role)
    return LoginResponse(access_token=token, role=user.role, username=user.username)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_RATE_LIMIT, key_func=login_rate_key)
async def register(
    request: Request,
    body: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    """Public self-registration. Always creates a REQUESTER and auto-logs in.

    The role is forced — the client cannot escalate to admin here (only
    ``POST /api/users`` can, and that is admin-gated). 403 when open
    registration is disabled; 409 on a duplicate username; throttled per
    (ip, username) like login. Returns a JWT so the UI logs in immediately.
    """
    if not get_settings().allow_open_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Open registration is disabled",
        )
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=UserRole.REQUESTER,
        email=body.email,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        ) from exc
    token = create_access_token(sub=user.id, role=user.role)
    return LoginResponse(access_token=token, role=user.role, username=user.username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    """Stateless logout: server-side no-op for v1; client discards the token."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)
