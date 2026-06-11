"""Injection/format guards on driver-bound free-text fields.

Free text that reaches device config (Jinja CLI templates render with
autoescape=False; a newline starts a NEW config command) must never carry
CR/LF. IP-shaped fields must actually parse as addresses so a bad value fails
at file time, not at apply time on the device.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from northbound.schemas.driver import (
    L3Change,
    LagChange,
    OspfChange,
    PortChange,
    VlanChange,
    VrfChange,
)

# --- CR/LF rejection: the CLI-injection vector -------------------------------


def test_port_description_rejects_newline_injection() -> None:
    with pytest.raises(ValidationError):
        PortChange(description="server-07\nno shutdown\nusername evil privilege 15")


def test_port_description_rejects_carriage_return() -> None:
    with pytest.raises(ValidationError):
        PortChange(description="x\rno shutdown")


def test_port_description_plain_text_ok() -> None:
    assert PortChange(description="app-server-07 | rack 3").description is not None


def test_port_description_length_capped() -> None:
    with pytest.raises(ValidationError):
        PortChange(description="x" * 257)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "create", "vlan_id": 10, "name": "evil\nvlan 999"},
        {"action": "create", "vlan_id": 10, "description": "a\nb"},
    ],
)
def test_vlan_change_rejects_crlf(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        VlanChange(**kwargs)


def test_vrf_change_rejects_crlf_name() -> None:
    with pytest.raises(ValidationError):
        VrfChange(action="create", name="t\nip route 0.0.0.0/0 192.0.2.99")


def test_l3_change_rejects_crlf_vrf() -> None:
    with pytest.raises(ValidationError):
        L3Change(action="create", kind="loopback", name="lo1", ipv4="192.0.2.1/30", vrf="a\nb")


def test_ospf_interface_rejects_crlf() -> None:
    with pytest.raises(ValidationError):
        OspfChange(action="set", target="interface", interface="vlan10\nx", area="0.0.0.0")


# --- IP-shaped field format validation (M-4) ---------------------------------


def test_l3_ipv4_must_be_cidr_interface() -> None:
    with pytest.raises(ValidationError):
        L3Change(action="create", kind="svi", vlan_id=10, ipv4="not-an-ip")
    ok = L3Change(action="create", kind="svi", vlan_id=10, ipv4="192.0.2.1/24")
    assert ok.ipv4 == "192.0.2.1/24"


def test_l3_ipv6_cidr_accepted() -> None:
    ok = L3Change(action="create", kind="svi", vlan_id=10, ipv4="2001:db8::1/64")
    assert ok.ipv4 == "2001:db8::1/64"


def test_ospf_router_id_must_be_dotted_quad() -> None:
    with pytest.raises(ValidationError):
        OspfChange(action="set", target="router-id", router_id="evil")
    ok = OspfChange(action="set", target="router-id", router_id="10.0.0.1")
    assert ok.router_id == "10.0.0.1"


def test_ospf_area_dotted_or_int() -> None:
    OspfChange(action="set", target="interface", interface="vlan10", area="0.0.0.0")
    OspfChange(action="set", target="interface", interface="vlan10", area="0")
    with pytest.raises(ValidationError):
        OspfChange(action="set", target="interface", interface="vlan10", area="evil")


# --- LagChange: DISABLED write scaffold, but its DTO still validates ----------
# (No driver renders a LAG change — see test_contract.py — but the payload shape
#  is hardened now so the FUTURE lab-validated write inherits clean input.)


def test_lag_change_create_valid() -> None:
    c = LagChange(
        action="create",
        name="ae0",
        members=["te-1/1/1", "te-1/1/2"],
        lacp_mode="active",
        lacp_rate="fast",
    )
    assert c.name == "ae0" and c.members == ("te-1/1/1", "te-1/1/2")
    assert c.lacp_mode == "active" and c.lacp_rate == "fast"


def test_lag_change_delete_needs_only_name() -> None:
    c = LagChange(action="delete", name="Po1")
    assert c.action == "delete" and c.members == ()


def test_lag_change_create_requires_members() -> None:
    with pytest.raises(ValidationError):
        LagChange(action="create", name="ae0")


def test_lag_change_rejects_crlf_name() -> None:
    with pytest.raises(ValidationError):
        LagChange(action="create", name="ae0\nno shutdown", members=["te-1/1/1"])


def test_lag_change_rejects_crlf_member() -> None:
    with pytest.raises(ValidationError):
        LagChange(action="create", name="ae0", members=["te-1/1/1\nevil"])


def test_lag_change_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        LagChange(action="create", name="", members=["te-1/1/1"])


def test_lag_change_rejects_bad_lacp_mode() -> None:
    with pytest.raises(ValidationError):
        LagChange(action="create", name="ae0", members=["te-1/1/1"], lacp_mode="bogus")
