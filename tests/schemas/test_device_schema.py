"""CredentialsIn → Credentials mapping (API boundary)."""

from __future__ import annotations

from northbound.schemas.device import CredentialsIn


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
