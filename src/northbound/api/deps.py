"""FastAPI dependencies for authentication and role-based access control.

``get_current_user`` extracts the bearer token, decodes it, and loads the
backing user row. ``require_admin`` layers a role check on top. Both raise the
appropriate HTTP status (401 / 403) with non-leaky messages.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.auth.cookies import ACCESS_COOKIE
from northbound.auth.jwt import InvalidToken, decode_token
from northbound.db import get_session
from northbound.models.enums import UserRole
from northbound.models.user import User

# auto_error=False so we raise our own 401 (consistent shape) on a missing header.
_bearer_scheme = HTTPBearer(auto_error=False)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Resolve the current user from the access token.

    The token is read from the ``nb_access`` httpOnly cookie (browser sessions)
    or, failing that, the ``Authorization: Bearer`` header (API clients/tests).
    Raises 401 if absent, invalid/expired, the wrong token type, or the user no
    longer exists.
    """
    token = request.cookies.get(ACCESS_COOKIE) or (credentials.credentials if credentials else None)
    if not token:
        raise _CREDENTIALS_EXCEPTION

    try:
        payload = decode_token(token, expected_type="access")
    except InvalidToken as exc:
        raise _CREDENTIALS_EXCEPTION from exc

    user = await session.scalar(select(User).where(User.id == payload.sub))
    if user is None:
        raise _CREDENTIALS_EXCEPTION
    # Token-version check: a password change/reset bumps User.token_version,
    # which revokes every token minted before it (the only way to invalidate
    # stateless JWTs). Old pre-claim tokens default ver=0, matching the
    # column's backfill default, so sessions survive the upgrade itself.
    if payload.ver != user.token_version:
        raise _CREDENTIALS_EXCEPTION
    # Disabled accounts cannot authenticate. Checked here rather than only at
    # login so an already-issued token stops working the moment the account is
    # disabled — disabling also bumps token_version, so this is belt-and-braces
    # against any future path that forgets to.
    if not user.is_active:
        raise _CREDENTIALS_EXCEPTION
    # Stash the verified subject for the write rate-limiter's key func (it runs
    # after dependencies): avoids a second JWT decode per write, and gives
    # cookie-authenticated browser sessions (no Authorization header) a
    # per-user key instead of collapsing onto a shared NAT/proxy IP.
    request.state.auth_sub = payload.sub
    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Allow only admin users; raise 403 otherwise."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
