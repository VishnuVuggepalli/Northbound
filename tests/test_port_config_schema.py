"""PortConfigIn validation — VLAN writes must carry an explicit port_mode."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from northbound.schemas.port import PortConfigIn


def test_mtu_only_ok() -> None:
    assert PortConfigIn(mtu=9216).mtu == 9216


def test_enabled_only_ok() -> None:
    assert PortConfigIn(enabled=False).enabled is False


def test_vlan_with_explicit_mode_ok() -> None:
    c = PortConfigIn(port_mode="trunk", untagged_vlan=1010, tagged_vlans=[1002])
    assert c.port_mode == "trunk"


def test_empty_body_rejected() -> None:
    with pytest.raises(ValidationError):
        PortConfigIn()


def test_untagged_without_mode_rejected() -> None:
    # The footgun: untagged-only with no port_mode would let the driver infer the
    # mode and could flip a trunk to access. Must be rejected at the boundary.
    with pytest.raises(ValidationError):
        PortConfigIn(untagged_vlan=1010)


def test_tagged_without_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        PortConfigIn(tagged_vlans=[1002, 1003])
