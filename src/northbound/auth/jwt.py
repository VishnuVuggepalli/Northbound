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


def create_access_token(
    sub: str,
    role: UserRole,
    expiry: dt.timedelta | None = None,
    *,
    settings: Settings | None = None,
) -> str:
    """Mint a signed HS256 JWT for ``sub`` with ``role`` and an expiry claim."""
    resolved = settings if settings is not None else get_settings()
    key = _resolve_secret_key(resolved)
    window = expiry if expiry is not None else dt.timedelta(minutes=resolved.jwt_expiry_minutes)
    expires_at = dt.datetime.now(tz=dt.UTC) + window
    claims: dict[str, str | int] = {
        "sub": sub,
        "role": role.value,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, key, algorithm=resolved.jwt_algorithm)
    return cast(str, token)


def decode_token(token: str, *, settings: Settings | None = None) -> TokenPayload:
    """Verify and decode ``token``; raise :class:`InvalidToken` on any failure."""
    resolved = settings if settings is not None else get_settings()
    key = _resolve_secret_key(resolved)
    try:
        raw = jwt.decode(token, key, algorithms=[resolved.jwt_algorithm])
    except JWTError as exc:  # bad signature, expired, malformed, wrong alg, ...
        raise InvalidToken(str(exc)) from exc

    # ``raw`` is untyped (dict from an untyped lib); validate it into a model.
    claims = cast(dict[str, object], raw)
    try:
        return TokenPayload.model_validate(claims)
    except ValidationError as exc:
        raise InvalidToken("token claims failed validation") from exc
