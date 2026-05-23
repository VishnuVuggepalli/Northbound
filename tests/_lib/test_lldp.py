"""LLDP normalizer behavior."""

from __future__ import annotations

from northbound._lib.lldp import (
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
