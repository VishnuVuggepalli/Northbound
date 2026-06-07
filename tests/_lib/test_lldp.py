"""LLDP normalizer behavior."""

from __future__ import annotations

from northbound._lib.lldp import (
    encode_local_port_prefix,
    local_port_matches,
    normalize_chassis_id,
    normalize_port_id,
    parse_snmp_lldp_table,
)
from northbound.schemas.driver import Neighbor


def test_chassis_id_mac_subtype_returns_colon_mac() -> None:
    raw = bytes.fromhex("aabbccddee01")
    assert normalize_chassis_id(raw, subtype=4) == "aa:bb:cc:dd:ee:01"


def test_chassis_id_string_subtype_returns_text() -> None:
    assert normalize_chassis_id(b"switch-01", subtype=7) == "switch-01"


def test_chassis_id_accepts_plain_str() -> None:
    assert normalize_chassis_id("switch-01", subtype=7) == "switch-01"


def test_port_id_mac_subtype_returns_colon_mac() -> None:
    raw = bytes.fromhex("001122334455")
    assert normalize_port_id(raw, subtype=3) == "00:11:22:33:44:55"


def test_port_id_ifindex_subtype_returns_decimal() -> None:
    assert normalize_port_id(b"42", subtype=2) == "42"


def test_port_id_interface_name_returns_text() -> None:
    assert normalize_port_id(b"Ethernet1", subtype=5) == "Ethernet1"


def test_port_id_strips_literal_surrounding_quotes() -> None:
    # Arista eAPI returns interfaceId wrapped in literal quotes (live on vEOS).
    assert normalize_port_id('"Ethernet1"') == "Ethernet1"
    assert normalize_port_id("'Ethernet1'") == "Ethernet1"
    # Don't strip non-matching / interior quotes.
    assert normalize_port_id('Eth"1') == 'Eth"1'


def test_parse_snmp_lldp_table_builds_neighbors() -> None:
    rows = [
        {
            "chassis_id": bytes.fromhex("aabbccddee01"),
            "chassis_id_subtype": 4,
            "port_id": b"Ethernet1",
            "port_id_subtype": 5,
            "system_name": b"r720-01",
            "system_description": b"Dell R720",
        },
        {
            "chassis_id": bytes.fromhex("aabbccddee02"),
            "chassis_id_subtype": 4,
            "port_id": b"Ethernet2",
            "port_id_subtype": 5,
            "system_name": b"r720-02",
        },
    ]
    neighbors = parse_snmp_lldp_table(rows)
    assert len(neighbors) == 2
    assert isinstance(neighbors[0], Neighbor)
    assert neighbors[0].chassis_id == "aa:bb:cc:dd:ee:01"
    assert neighbors[0].port_id == "Ethernet1"
    assert neighbors[0].system_name == "r720-01"
    assert neighbors[0].system_description == "Dell R720"
    assert neighbors[1].system_description is None


def test_parse_snmp_lldp_table_empty() -> None:
    assert parse_snmp_lldp_table([]) == []


def test_encode_local_port_prefix() -> None:
    assert encode_local_port_prefix("Eth1") == "[Eth1] "
    assert encode_local_port_prefix("") == ""  # no port → no prefix


def test_local_port_matches_is_exact_not_substring() -> None:
    # The encode/match pair round-trips and disambiguates Eth1 / Eth1/1 / Eth10.
    desc1 = encode_local_port_prefix("Eth1") + "host-a"
    desc11 = encode_local_port_prefix("Eth1/1") + "host-b"
    desc10 = encode_local_port_prefix("Eth10") + "host-c"
    assert local_port_matches(desc1, "Eth1") is True
    assert local_port_matches(desc11, "Eth1") is False  # substring would wrongly match
    assert local_port_matches(desc10, "Eth1") is False
    assert local_port_matches(desc11, "Eth1/1") is True
    assert local_port_matches(desc10, "Eth10") is True
    assert local_port_matches(None, "Eth1") is False
    assert local_port_matches("no-prefix-desc", "Eth1") is False
