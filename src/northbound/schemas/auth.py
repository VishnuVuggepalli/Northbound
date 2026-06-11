"""Pydantic v2 DTOs for the auth + users API surface.

These are the *only* shapes that cross the HTTP boundary. ``password_hash`` is
deliberately absent from every response model so it can never be serialised
out of the service.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from northbound.models.enums import UserRole


class LoginRequest(BaseModel):
    """Body of ``POST /api/auth/login``."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    """Successful login result. ``token_type`` is always ``bearer``."""

    access_token: str
    token_type: str = "bearer"
    role: UserRole
    username: str


class TokenPayload(BaseModel):
    """Decoded JWT claims. ``sub`` is the user id; ``exp`` is a UNIX timestamp.

    ``type`` distinguishes access vs refresh tokens; it defaults to ``access`` so
    legacy tokens minted before the split still validate as access tokens.
    """

    sub: str
    role: UserRole
    exp: int
    type: str = "access"
    # Token-version: must match User.token_version or the token is rejected —
    # bumping the column on a password change/reset revokes every issued token.
    # Defaults 0 so tokens minted before the claim existed stay valid until the
    # user's first password change.
    ver: int = 0


class UserOut(BaseModel):
    """Public view of a user. NEVER includes ``password_hash``."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: UserRole
    email: str | None = None


class UserCreate(BaseModel):
    """Body of ``POST /api/users`` (admin only)."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1)
    role: UserRole
    email: EmailStr | None = Field(default=None, max_length=256)


class PasswordChangeIn(BaseModel):
    """Body of ``POST /api/users/me/password`` (self-service).

    Requires the current password so a hijacked session can't silently take
    over the account. Same floor as registration for the new secret.
    """

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=256)


class PasswordResetIn(BaseModel):
    """Body of ``POST /api/users/{user_id}/password-reset`` (admin only)."""

    new_password: str = Field(min_length=8, max_length=256)


class RegisterRequest(BaseModel):
    """Body of ``POST /api/auth/register`` (public self-registration).

    The role is intentionally absent — self-registered accounts are always
    REQUESTER; only an admin can mint privileged users via ``POST /api/users``.
    A longer password floor than login applies because this creates the secret.
    """

    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    email: EmailStr | None = Field(default=None, max_length=256)
