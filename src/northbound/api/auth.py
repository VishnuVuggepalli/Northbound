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
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.limiter import LOGIN_RATE_LIMIT, limiter
from northbound.auth.jwt import create_access_token
from northbound.auth.password import verify_password
from northbound.db import get_session
from northbound.models.user import User
from northbound.schemas.auth import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Single generic message — never reveals whether the username exists.
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect username or password",
)


@router.post("/login", response_model=LoginResponse)
@limiter.limit(LOGIN_RATE_LIMIT)
async def login(
    request: Request,
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LoginResponse:
    """Verify credentials and issue a JWT. 401 (generic) on any mismatch."""
    user = await session.scalar(select(User).where(User.username == body.username))

    # Verify even when the user is missing? We cannot (no hash), but we still
    # return the identical generic error so timing/response don't reveal which
    # branch failed.
    if user is None or not verify_password(body.password, user.password_hash):
        raise _INVALID_CREDENTIALS

    token = create_access_token(sub=user.id, role=user.role)
    return LoginResponse(access_token=token, role=user.role, username=user.username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    """Stateless logout: server-side no-op for v1; client discards the token."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)
