"""CredentialsIn → Credentials mapping (API boundary)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from northbound.schemas.device import (
    ConnectionTestIn,
    CredentialsIn,
    DeviceCreateIn,
    DiscoverIn,
)


def test_to_credentials_threads_all_fields_including_enable_secret() -> None:
    """Every inbound credential field — including ``enable_secret`` — reaches the
    in-process Credentials value object. Guards against the field being dropped
    at the API boundary (which would make the Arista enable-secret path dead)."""
    cin = CredentialsIn(
        username="admin",
        password="pw",
        ssh_private_key="-----KEY-----",
        api_token="tok",
        snmp_community="public",
        enable_secret="en4ble",
    )
    creds = cin.to_credentials()
    assert creds.username == "admin"
    assert creds.password == "pw"
    assert creds.ssh_private_key == "-----KEY-----"
    assert creds.api_token == "tok"
    assert creds.snmp_community == "public"
    assert creds.enable_secret == "en4ble"


def test_to_credentials_enable_secret_defaults_none() -> None:
    """Unset enable_secret defaults to None (bare 'enable' path on Arista)."""
    creds = CredentialsIn(username="admin").to_credentials()
    assert creds.enable_secret is None


# --------------------------------------------------------------------------- #
# Device name — RFC 1123 hostname validation
# --------------------------------------------------------------------------- #
def _create(name: str) -> DeviceCreateIn:
    return DeviceCreateIn(
        name=name,
        environment="lab",
        role="leaf",
        platform_id="mock",
        mgmt_ip="10.0.0.1",
    )


@pytest.mark.parametrize(
    "name",
    [
        "lab-leaf-1",
        "lab-1",
        "dc-1",
        "core-router",
        "mock-switch-01",
        "will-not-exist",
        "a",
        "spine01.fabric.example",  # multi-label FQDN
        "Leaf-2",  # case-insensitive: uppercase allowed
    ],
)
def test_device_name_accepts_valid_hostnames(name: str) -> None:
    assert _create(name).name == name


@pytest.mark.parametrize(
    "name",
    [
        "-leaf",  # leading hyphen
        "leaf-",  # trailing hyphen
        "leaf 02",  # whitespace
        "leaf\t2",  # control char
        "leaf_02",  # underscore not allowed in a hostname label
        "a..b",  # empty label
        "x" * 64,  # label > 63 chars
        "no shutdown\nusername evil",  # newline injection
        "bad/slash",
    ],
)
def test_device_name_rejects_non_hostnames(name: str) -> None:
    with pytest.raises(ValidationError):
        _create(name)


def test_device_name_rejects_over_253_total() -> None:
    label = "a" * 63
    too_long = ".".join([label, label, label, label])  # 4*63 + 3 = 255 > 253
    with pytest.raises(ValidationError):
        _create(too_long)


def test_connection_test_and_discover_validate_no_name() -> None:
    """ConnectionTestIn / DiscoverIn carry NO device name field — they are pure
    probe payloads (mgmt_ip only). Constructing them must still succeed."""
    body = ConnectionTestIn(platform_id="mock", mgmt_ip="10.0.0.1")
    assert body.mgmt_ip == "10.0.0.1"
    disc = DiscoverIn(platform_id="mock", mgmt_ip="10.0.0.1")
    assert disc.mgmt_ip == "10.0.0.1"
