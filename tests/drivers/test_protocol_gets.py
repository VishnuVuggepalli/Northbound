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


# FRR `show ip bgp summary` — PicOS routing is FRR. Sample from FRR docs
# (https://docs.frrouting.org/en/latest/bgp.html), incl. an IPv6 peer + a
# non-Established (Active) peer. Doc-derived; pending live confirm on a BGP leaf.
_BGP_SUMMARY = """IPv4 Unicast Summary:
BGP router identifier 10.10.10.1, local AS number 65001 VRF default vrf-id 0
BGP table version 4
RIB entries 7, using 1344 bytes of memory
Peers 2, using 43 KiB of memory

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd   PfxSnt Desc
192.168.0.2     4      65002         8        10        0    0    0 00:03:09            5 (Policy) N/A
10.0.0.6        4      65003        90        88        0    0    0 00:40:00         Active N/A
fe80:1::2222    4      65002         9        11        0    0    0 00:03:09            3 (Policy) N/A

Total number of neighbors 3
"""


def test_parse_bgp_summary_frr() -> None:
    t = parse_table("Summary", "show_ip_bgp_summary.textfsm", _BGP_SUMMARY)
    assert t.columns[0] == "Neighbor" and "State Pfxrcd" in t.columns
    assert len(t.rows) == 3
    assert t.rows[0][0] == "192.168.0.2" and t.rows[0][2] == "65002"
    # non-Established peer shows the state word, not a prefix count
    assert t.rows[1][0] == "10.0.0.6" and t.rows[1][-1] == "Active"
    # IPv6 peer parses
    assert t.rows[2][0] == "fe80:1::2222"


def test_bgp_registered() -> None:
    assert "BGP" in PROTOCOL_GETS
    assert any(g.command == "show ip bgp summary" for g in PROTOCOL_GETS["BGP"])
