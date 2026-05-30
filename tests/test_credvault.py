"""Tests for CredVault: encryption round-trip, serialization, failure modes."""

from __future__ import annotations

import logging

import pytest
from cryptography.fernet import Fernet

from northbound.config import Settings
from northbound.schemas.driver import Credentials
from northbound.services.credvault import (
    DecryptionError,
    FernetCredVault,
    MasterKeyMissing,
    deserialize_credentials,
    serialize_credentials,
)


@pytest.fixture
def vault() -> FernetCredVault:
    return FernetCredVault(Fernet.generate_key())


def test_encrypt_decrypt_round_trip(vault: FernetCredVault) -> None:
    plaintext = b"super-secret-token"
    blob = vault.encrypt(plaintext)
    assert blob != plaintext
    assert vault.decrypt(blob) == plaintext


def test_credentials_serialize_round_trip(vault: FernetCredVault) -> None:
    creds = Credentials(
        username="admin",
        password="hunter2",
        snmp_community="public",
    )
    blob = serialize_credentials(creds, vault)
    assert b"hunter2" not in blob  # ciphertext, not plaintext
    restored = deserialize_credentials(blob, vault)
    assert restored == creds


def test_tampered_ciphertext_raises(vault: FernetCredVault) -> None:
    blob = vault.encrypt(b"payload")
    tampered = blob[:-1] + (b"A" if blob[-1:] != b"A" else b"B")
    with pytest.raises(DecryptionError):
        vault.decrypt(tampered)


def test_wrong_key_fails(vault: FernetCredVault) -> None:
    blob = vault.encrypt(b"payload")
    other = FernetCredVault(Fernet.generate_key())
    with pytest.raises(DecryptionError):
        other.decrypt(blob)


def test_deserialize_tolerates_unknown_and_missing_fields(
    vault: FernetCredVault,
) -> None:
    blob = serialize_credentials(Credentials(username="u"), vault)
    creds = deserialize_credentials(blob, vault)
    assert creds.username == "u"
    assert creds.password is None  # default preserved


def test_missing_key_outside_dev_raises() -> None:
    settings = Settings(environment="production", master_key=None)
    with pytest.raises(MasterKeyMissing):
        FernetCredVault.from_settings(settings)


def test_missing_key_in_dev_generates_ephemeral(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(environment="development", master_key=None)
    with caplog.at_level(logging.WARNING, logger="northbound.credvault"):
        vault = FernetCredVault.from_settings(settings)
    # ephemeral key works for a round-trip
    assert vault.decrypt(vault.encrypt(b"x")) == b"x"
    assert any("EPHEMERAL" in r.message for r in caplog.records)


def test_explicit_key_from_settings_used() -> None:
    key = Fernet.generate_key().decode("utf-8")
    settings = Settings(environment="production", master_key=key)
    vault = FernetCredVault.from_settings(settings)
    assert vault.decrypt(vault.encrypt(b"y")) == b"y"
