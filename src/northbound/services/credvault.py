"""Credential vault — encrypt device credentials at rest.

``CredVault`` is the interface; ``FernetCredVault`` is the default symmetric
implementation (cryptography's Fernet = AES-128-CBC + HMAC-SHA256). A
production deployment can swap in a KMS/Vault-backed impl behind the same
Protocol with no caller changes.

Hard rules enforced here:
- Plaintext credentials are NEVER logged.
- The master key is NEVER logged.
- Outside development, a missing master key is a hard startup failure; in
  development an ephemeral key is generated with a loud warning (so dev never
  silently persists data it can't later decrypt across restarts).
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import asdict
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken

from northbound.config import Settings, get_settings
from northbound.schemas.driver import Credentials

logger = logging.getLogger("northbound.credvault")


class CredVaultError(Exception):
    """Base class for credential-vault failures."""


class MasterKeyMissing(CredVaultError):
    """No master key configured outside a development environment."""


class DecryptionError(CredVaultError):
    """Ciphertext failed to decrypt (tampered, wrong key, or corrupt)."""


@runtime_checkable
class CredVault(Protocol):
    """Symmetric encrypt/decrypt boundary for credentials at rest."""

    def encrypt(self, plaintext: bytes) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> bytes: ...


def _resolve_master_key(settings: Settings) -> bytes:
    """Return the Fernet key bytes, applying the dev/prod key policy.

    Never logs the key value. In production a missing key raises; in dev an
    ephemeral key is minted with a warning.
    """
    if settings.master_key:
        # Fernet validates the key on first use; pass through as-is.
        return settings.master_key.encode("utf-8")

    if settings.environment != "development":
        raise MasterKeyMissing(
            f"NB_MASTER_KEY is required outside development (environment={settings.environment!r})"
        )

    ephemeral = Fernet.generate_key()
    logger.warning(
        "NB_MASTER_KEY not set; generated an EPHEMERAL development key. "
        "Encrypted credentials will NOT survive a process restart. "
        "Set NB_MASTER_KEY for any persistent use."
    )
    return ephemeral


class FernetCredVault:
    """Fernet-backed :class:`CredVault`."""

    def __init__(self, key: bytes) -> None:
        # Raises ValueError on a malformed key — fail fast at construction.
        self._fernet = Fernet(key)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> FernetCredVault:
        resolved = settings if settings is not None else get_settings()
        return cls(_resolve_master_key(resolved))

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            # Do not include ciphertext/key in the message.
            raise DecryptionError("credential decryption failed") from exc


# ---------------------------------------------------------------------------
# Credentials (de)serialization helpers
# ---------------------------------------------------------------------------


def serialize_credentials(creds: Credentials, vault: CredVault) -> bytes:
    """JSON-encode and encrypt a Credentials value into an opaque blob."""
    payload = json.dumps(asdict(creds), separators=(",", ":"), sort_keys=True)
    return vault.encrypt(payload.encode("utf-8"))


def deserialize_credentials(blob: bytes, vault: CredVault) -> Credentials:
    """Decrypt and JSON-decode a blob back into a Credentials value.

    Unknown keys are dropped and missing keys fall back to dataclass
    defaults, so the blob format tolerates additive schema changes.
    """
    plaintext = vault.decrypt(blob)
    raw = json.loads(plaintext.decode("utf-8"))
    if not isinstance(raw, dict):
        raise DecryptionError("decrypted credential payload was not an object")
    fields = {f.name for f in dataclasses.fields(Credentials)}
    known = {k: v for k, v in raw.items() if k in fields}
    return Credentials(**known)
