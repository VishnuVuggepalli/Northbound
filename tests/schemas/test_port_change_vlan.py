"""PortChange 802.1Q VLAN-range validation at the API boundary.

Valid VLAN IDs are 1..4094; 0 and 4095 are reserved and must be rejected.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from northbound.schemas.driver import PortChange


def test_untagged_vlan_accepts_lower_and_upper_bounds() -> None:
    """1 and 4094 are the inclusive valid bounds for untagged_vlan."""
    assert PortChange(untagged_vlan=1).untagged_vlan == 1
    assert PortChange(untagged_vlan=4094).untagged_vlan == 4094


def test_untagged_vlan_none_allowed() -> None:
    """untagged_vlan stays optional (None = no change)."""
    assert PortChange().untagged_vlan is None
    assert PortChange(untagged_vlan=None).untagged_vlan is None


@pytest.mark.parametrize("bad", [0, 4095, -1])
def test_untagged_vlan_rejects_out_of_range(bad: int) -> None:
    """0, 4095, and negatives are reserved/invalid and rejected."""
    with pytest.raises(ValidationError):
        PortChange(untagged_vlan=bad)


def test_tagged_vlans_accepts_bounds_and_none() -> None:
    """tagged_vlans accepts each item in 1..4094, and None overall."""
    assert PortChange(tagged_vlans=[1, 4094]).tagged_vlans == [1, 4094]
    assert PortChange(tagged_vlans=None).tagged_vlans is None


@pytest.mark.parametrize("bad", [0, 4095, -1])
def test_tagged_vlans_rejects_out_of_range_item(bad: int) -> None:
    """A single out-of-range VLAN in the list fails validation."""
    with pytest.raises(ValidationError):
        PortChange(tagged_vlans=[10, bad])
