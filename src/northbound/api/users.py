"""Users router — self lookup and admin-only user management.

``UserOut`` never carries ``password_hash``, so no response can leak it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.deps import get_current_user, require_admin
from northbound.api.limiter import limiter, write_rate_key, write_rate_limit_provider
from northbound.auth.password import hash_password
from northbound.db import get_session
from northbound.models.user import User
from northbound.schemas.auth import UserCreate, UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def read_me(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the currently authenticated user."""
    return user


@router.get("", response_model=list[UserOut])
async def list_users(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[User]:
    """List all users (admin only)."""
    result = await session.scalars(select(User).order_by(User.username))
    return list(result.all())


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def create_user(
    request: Request,
    body: UserCreate,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Create a user with a hashed password (admin only). 409 on duplicate name."""
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
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
    return user
