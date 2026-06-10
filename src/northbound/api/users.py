"""Users router — self lookup and admin-only user management.

``UserOut`` never carries ``password_hash``, so no response can leak it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northbound.api.deps import get_current_user, require_admin
from northbound.api.limiter import limiter, write_rate_key, write_rate_limit_provider
from northbound.auth.cookies import set_session_cookies
from northbound.auth.jwt import create_access_token, create_refresh_token
from northbound.auth.password import hash_password, verify_password
from northbound.config import get_settings
from northbound.db import get_session
from northbound.models.user import User
from northbound.schemas.auth import PasswordChangeIn, PasswordResetIn, UserCreate, UserOut
from northbound.services import audit

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


@router.post("/me/password", response_model=UserOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def change_my_password(
    request: Request,
    response: Response,
    body: PasswordChangeIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Self-service password change (any role).

    Requires the CURRENT password so a hijacked cookie alone can't take over
    the account. Bumps ``token_version`` — revoking every session issued
    before the change — then re-issues fresh cookies so the caller stays
    logged in. Audited without any secret material.
    """
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    session.add(user)
    await audit.append_audit(
        session,
        user_id=user.id,
        action="user.password_changed",
        result="ok",
    )
    await session.flush()
    # Fresh session for the changing client (its old token just got revoked).
    access = create_access_token(sub=user.id, role=user.role, token_version=user.token_version)
    refresh = create_refresh_token(sub=user.id, role=user.role, token_version=user.token_version)
    set_session_cookies(
        response, access_token=access, refresh_token=refresh, settings=get_settings()
    )
    return user


@router.post("/{user_id}/password-reset", response_model=UserOut)
@limiter.limit(write_rate_limit_provider, key_func=write_rate_key)
async def reset_user_password(
    request: Request,
    user_id: str,
    body: PasswordResetIn,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Admin sets a NEW password for a user (the old one is never recoverable —
    passwords are one-way bcrypt hashes). Bumps ``token_version`` so every one
    of the target's existing sessions is kicked. Audited (actor + target, no
    secret material)."""
    target = await session.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target.password_hash = hash_password(body.new_password)
    target.token_version += 1
    session.add(target)
    await audit.append_audit(
        session,
        user_id=admin.id,
        action="user.password_reset",
        after={"target_user": target.username},
        result="ok",
    )
    await session.flush()
    return target


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
