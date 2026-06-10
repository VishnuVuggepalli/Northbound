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
from northbound.auth.cookies import REFRESH_COOKIE, clear_session_cookies, set_session_cookies
from northbound.auth.jwt import (
    InvalidToken,
    create_access_token,
    create_refresh_token,
    decode_token,
)
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
_INVALID_REFRESH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired session",
)


def _issue_session(response: Response, user: User) -> LoginResponse:
    """Mint an access + refresh token, set the httpOnly cookies, and return the
    login body. The body still carries ``access_token`` for API/Bearer clients
    (and tests); browsers use the cookie and ignore it."""
    access = create_access_token(sub=user.id, role=user.role, token_version=user.token_version)
    refresh = create_refresh_token(sub=user.id, role=user.role, token_version=user.token_version)
    set_session_cookies(
        response, access_token=access, refresh_token=refresh, settings=get_settings()
    )
    return LoginResponse(access_token=access, role=user.role, username=user.username)


@router.post("/login", response_model=LoginResponse)
@limiter.limit(LOGIN_RATE_LIMIT, key_func=login_rate_key)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    """Verify credentials, set session cookies, and return the login body.

    401 (generic) on any mismatch.
    """
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

    return _issue_session(response, user)


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_RATE_LIMIT, key_func=login_rate_key)
async def register(
    request: Request,
    response: Response,
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
    return _issue_session(response, user)


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    """Rotate the session from the refresh cookie: issue a new access + refresh
    pair (rotation) and re-set both cookies. 401 if the refresh cookie is
    missing/invalid/expired or the user is gone."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise _INVALID_REFRESH
    try:
        payload = decode_token(token, expected_type="refresh")
    except InvalidToken as exc:
        raise _INVALID_REFRESH from exc
    user = await session.scalar(select(User).where(User.id == payload.sub))
    if user is None:
        raise _INVALID_REFRESH
    # A stale refresh token (minted before a password change bumped the
    # version) must not be able to mint fresh sessions — that would defeat
    # the revocation entirely.
    if payload.ver != user.token_version:
        raise _INVALID_REFRESH
    return _issue_session(response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> Response:
    """Clear the session cookies. (Tokens are stateless, so this is the session
    end for cookie clients; Bearer clients simply drop their token.)"""
    clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
