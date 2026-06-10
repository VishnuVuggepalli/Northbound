"""JWT issuance and verification via python-jose (HS256).

python-jose ships no type stubs, so its ``encode``/``decode`` are seen as
untyped at this boundary. We wrap them with explicit annotations and validate
the decoded claims through :class:`TokenPayload`, so nothing untyped escapes
this module.

Secret-key policy mirrors the CredVault master-key policy: outside development
a missing ``NB_SECRET_KEY`` is a hard failure; in development an ephemeral key
is minted with a loud warning (tokens won't survive a restart).
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from typing import cast

from jose import JWTError, jwt
from pydantic import ValidationError

from northbound.config import Settings, get_settings
from northbound.models.enums import UserRole
from northbound.schemas.auth import TokenPayload

logger = logging.getLogger("northbound.auth.jwt")


class AuthError(Exception):
    """Base class for auth-layer failures."""


class SecretKeyMissing(AuthError):
    """No JWT secret configured outside a development environment."""


class InvalidToken(AuthError):
    """Token is malformed, tampered, expired, or carries unexpected claims."""


# Process-lifetime ephemeral key for development when none is configured.
_EPHEMERAL_DEV_KEY = secrets.token_urlsafe(48)


def _resolve_secret_key(settings: Settings) -> str:
    """Return the JWT signing secret, applying the dev/prod key policy.

    Never logs the key value. Outside development a missing key raises; in dev
    a stable per-process ephemeral key is used with a warning.
    """
    if settings.secret_key:
        return settings.secret_key

    if settings.environment != "development":
        raise SecretKeyMissing(
            f"NB_SECRET_KEY is required outside development (environment={settings.environment!r})"
        )

    logger.warning(
        "NB_SECRET_KEY not set; using an EPHEMERAL development signing key. "
        "Issued JWTs will NOT survive a process restart. "
        "Set NB_SECRET_KEY for any persistent use."
    )
    return _EPHEMERAL_DEV_KEY


def _mint(
    sub: str,
    role: UserRole,
    *,
    token_type: str,
    window: dt.timedelta,
    settings: Settings | None,
    token_version: int = 0,
) -> str:
    resolved = settings if settings is not None else get_settings()
    key = _resolve_secret_key(resolved)
    expires_at = dt.datetime.now(tz=dt.UTC) + window
    claims: dict[str, str | int] = {
        "sub": sub,
        "role": role.value,
        "exp": int(expires_at.timestamp()),
        "type": token_type,
        # Must match User.token_version at verification time; bumping the
        # column on a password change revokes every previously-issued token.
        "ver": token_version,
    }
    return cast(str, jwt.encode(claims, key, algorithm=resolved.jwt_algorithm))


def create_access_token(
    sub: str,
    role: UserRole,
    expiry: dt.timedelta | None = None,
    *,
    settings: Settings | None = None,
    token_version: int = 0,
) -> str:
    """Mint a short-lived access JWT (``type=access``)."""
    resolved = settings if settings is not None else get_settings()
    window = expiry if expiry is not None else dt.timedelta(minutes=resolved.access_token_minutes)
    return _mint(
        sub,
        role,
        token_type="access",
        window=window,
        settings=settings,
        token_version=token_version,
    )


def create_refresh_token(
    sub: str,
    role: UserRole,
    expiry: dt.timedelta | None = None,
    *,
    settings: Settings | None = None,
    token_version: int = 0,
) -> str:
    """Mint a long-lived refresh JWT (``type=refresh``), used only at /auth/refresh."""
    resolved = settings if settings is not None else get_settings()
    window = expiry if expiry is not None else dt.timedelta(days=resolved.refresh_token_days)
    return _mint(
        sub,
        role,
        token_type="refresh",
        window=window,
        settings=settings,
        token_version=token_version,
    )


def decode_token(
    token: str, *, expected_type: str | None = None, settings: Settings | None = None
) -> TokenPayload:
    """Verify and decode ``token``; raise :class:`InvalidToken` on any failure.

    When ``expected_type`` is given, the token's ``type`` claim must match (so a
    refresh token can't be used as an access token or vice-versa).
    """
    resolved = settings if settings is not None else get_settings()
    key = _resolve_secret_key(resolved)
    try:
        raw = jwt.decode(token, key, algorithms=[resolved.jwt_algorithm])
    except JWTError as exc:  # bad signature, expired, malformed, wrong alg, ...
        raise InvalidToken(str(exc)) from exc

    # ``raw`` is untyped (dict from an untyped lib); validate it into a model.
    claims = cast(dict[str, object], raw)
    try:
        payload = TokenPayload.model_validate(claims)
    except ValidationError as exc:
        raise InvalidToken("token claims failed validation") from exc
    if expected_type is not None and payload.type != expected_type:
        raise InvalidToken(f"expected {expected_type} token, got {payload.type}")
    return payload
