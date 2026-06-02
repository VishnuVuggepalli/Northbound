"""TextFSM protocol-get parsing — templates validated against real PicOS output."""

from __future__ import annotations

from northbound.drivers._protocol_gets import PROTOCOL_GETS, parse_table

_OSPF_NEIGHBOR = """.
Neighbor ID     Pri State           Up Time         Dead Time Address         Interface                        RXmtL RqstL DBsmL
172.30.20.1       1 Full/DR         6d21h32m          37.012s 10.10.0.17      vlan1010:10.10.250.2                 0     0     0
172.30.0.254      1 Full/DROther    6d21h32m          35.394s 10.10.0.254     vlan1010:10.10.250.2                 0     0     0
"""

_ARP = """Aging-time(seconds): 1200
Total count        : 2
Address          HW Address         Type     Interface        Age
---------------  -----------------  -------  ---------------  -------
10.10.0.17       92:C9:F6:67:51:6A  Dynamic  vlan1010         574
10.10.0.254      64:9D:99:D9:83:AC  Dynamic  vlan1010         570
"""

_LLDP = """LLDP Remote Devices Information
LocalPort     ChassisId                 PortId             Management Address  Host Name           Capability
------------  ------------------------  -----------------  ------------------  ------------------  -----------------
xe-1/1/20     3C:FD:FE:DC:9C:38         3C:FD:FE:DC:9C:38
xe-1/1/25     98:5D:82:46:C8:3D         Ethernet52/1       192.168.89.11       leaf-03             B, R
"""


def test_parse_ospf_neighbor() -> None:
    t = parse_table("Neighbors", "show_ospf_neighbor.textfsm", _OSPF_NEIGHBOR)
    assert t.columns[0] == "Neighbor Id" and "State" in t.columns
    assert len(t.rows) == 2
    assert t.rows[0][0] == "172.30.20.1" and t.rows[0][2] == "Full/DR"


def test_parse_arp_drops_header_and_separator() -> None:
    t = parse_table("ARP", "show_arp.textfsm", _ARP)
    assert len(t.rows) == 2
    assert t.rows[0] == ("10.10.0.17", "92:C9:F6:67:51:6A", "Dynamic", "vlan1010", "574")


def test_parse_lldp_ragged_columns() -> None:
    t = parse_table("Neighbors", "show_lldp_neighbor.textfsm", _LLDP)
    assert len(t.rows) == 2
    # first row has empty trailing columns (no mgmt/host/cap)
    assert t.rows[0][0] == "xe-1/1/20"
    assert t.rows[1][4] == "leaf-03"


def test_registry_has_ospf_and_lldp() -> None:
    assert "OSPF" in PROTOCOL_GETS and "LLDP" in PROTOCOL_GETS
    assert any(g.command == "show ospf neighbor" for g in PROTOCOL_GETS["OSPF"])
