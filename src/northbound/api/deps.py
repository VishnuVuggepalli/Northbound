"""FastAPI dependencies for authentication and role-based access control.

``get_current_user`` extracts the bearer token, decodes it, and loads the
backing user row. ``require_admin`` layers a role check on top. Both raise the
appropriate HTTP status (401 / 403) with non-leaky messages.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Resolve the current user from the ``Authorization: Bearer`` token.

    Raises 401 if the header is missing, the token is invalid/expired, or the
    referenced user no longer exists.
    """
    if credentials is None or not credentials.credentials:
        raise _CREDENTIALS_EXCEPTION

    try:
        payload = decode_token(credentials.credentials)
    except InvalidToken as exc:
        raise _CREDENTIALS_EXCEPTION from exc

    user = await session.scalar(select(User).where(User.id == payload.sub))
    if user is None:
        raise _CREDENTIALS_EXCEPTION
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
