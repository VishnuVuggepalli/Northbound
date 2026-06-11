"""RFC-compliant validation of IP-address and email fields at the DTO boundary.

These guard the hardening that replaced "length only" checks with real
``ipaddress``-stdlib / Pydantic ``EmailStr`` validation:

- ``mgmt_ip`` on the device create/onboard DTOs (IPv4 or IPv6 address),
- ``bmc_ip`` on ``PortChange`` and ``PortMetadataPatchIn`` (optional IP),
- ``email`` on ``RegisterRequest`` and ``UserCreate`` (RFC 5322 via EmailStr).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from northbound.schemas.auth import RegisterRequest, UserCreate
from northbound.schemas.device import ConnectionTestIn, DeviceCreateIn
from northbound.schemas.driver import PortChange
from northbound.schemas.port import PortMetadataPatchIn

# --- mgmt_ip (device create + onboard) ---------------------------------------


def _device_create(mgmt_ip: str) -> DeviceCreateIn:
    return DeviceCreateIn(
        name="leaf-1",
        environment="dc1",
        role="leaf",
        platform_id="pica8",
        mgmt_ip=mgmt_ip,
    )


@pytest.mark.parametrize("ip", ["10.0.0.1", "192.168.1.254", "2001:db8::1", "::1"])
def test_mgmt_ip_accepts_valid_v4_and_v6(ip: str) -> None:
    assert _device_create(ip).mgmt_ip == ip
    # ConnectionTestIn shares the same validator.
    assert ConnectionTestIn(platform_id="pica8", mgmt_ip=ip).mgmt_ip == ip


@pytest.mark.parametrize("ip", ["not-an-ip", "999.1.1.1", "10.0.0.1/24", "10.0.0", "", "   "])
def test_mgmt_ip_rejects_garbage_and_cidr(ip: str) -> None:
    with pytest.raises(ValidationError):
        _device_create(ip)


# --- bmc_ip (PortChange + PortMetadataPatchIn) -------------------------------


@pytest.mark.parametrize("ip", ["10.0.0.55", "2001:db8::55"])
def test_bmc_ip_accepts_valid_ip(ip: str) -> None:
    assert PortChange(bmc_ip=ip).bmc_ip == ip
    assert PortMetadataPatchIn(bmc_ip=ip).bmc_ip == ip


@pytest.mark.parametrize("empty", ["", None])
def test_bmc_ip_allows_empty_to_clear(empty: str | None) -> None:
    # Empty/None means "clear/unset" and must remain valid.
    assert PortChange(bmc_ip=empty).bmc_ip == empty
    assert PortMetadataPatchIn(bmc_ip=empty).bmc_ip == empty


@pytest.mark.parametrize("ip", ["nope", "10.0.0.999", "10.0.0.55/24"])
def test_bmc_ip_rejects_garbage(ip: str) -> None:
    with pytest.raises(ValidationError):
        PortChange(bmc_ip=ip)
    with pytest.raises(ValidationError):
        PortMetadataPatchIn(bmc_ip=ip)


# --- email (RegisterRequest + UserCreate) ------------------------------------


@pytest.mark.parametrize("email", ["alice@example.com", "bob.smith+tag@sub.example.co"])
def test_email_accepts_valid(email: str) -> None:
    assert RegisterRequest(username="alice", password="hunter2pw", email=email)
    assert UserCreate(username="alice", password="hunter2pw", role="admin", email=email)


def test_email_optional_none_allowed() -> None:
    assert RegisterRequest(username="alice", password="hunter2pw").email is None
    assert UserCreate(username="alice", password="hunter2pw", role="admin").email is None


@pytest.mark.parametrize("email", ["not-an-email", "missing@tld", "@nouser.com", "a b@x.com"])
def test_email_rejects_malformed(email: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username="alice", password="hunter2pw", email=email)
    with pytest.raises(ValidationError):
        UserCreate(username="alice", password="hunter2pw", role="admin", email=email)
