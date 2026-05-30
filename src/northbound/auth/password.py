"""Password hashing via passlib's bcrypt backend.

A single module-level :class:`~passlib.context.CryptContext` is the only place
that knows the hashing scheme, so rotating the algorithm later is a one-line
change. ``deprecated="auto"`` lets passlib flag legacy hashes for rehashing.
"""

from __future__ import annotations

# passlib ships no type stubs; pyright emits a non-fatal reportMissingTypeStubs
# warning on this import. CryptContext is used through the typed wrapper below.
from passlib.context import CryptContext

# bcrypt is the only active scheme; ``deprecated="auto"`` future-proofs rotation.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of ``plain`` (salt is embedded in the output)."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff ``plain`` matches ``hashed``; never raises on bad input."""
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        # Malformed/unknown hash format — treat as a non-match, never crash auth.
        return False
