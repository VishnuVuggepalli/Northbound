"""Generic per-protocol operational "gets" — CLI show + TextFSM parse.

PicOS exposes no NETCONF operational state and no off-the-shelf parser library
covers it, so operational detail comes from CLI ``show`` over SSH, parsed by the
TextFSM library against templates we author (templates are declarative data; the
TextFSM engine does the parsing — no hand-rolled regex parsers).

A ``ProtocolGet`` binds a human title to a CLI command and a TextFSM template.
The registry maps a protocol (by its System-tab label) to its gets, so adding a
get for any protocol is a one-line registry entry + a template file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import textfsm

from northbound.schemas.driver import ProtocolTable

_TEMPLATE_DIR = Path(__file__).parent / "textfsm_templates" / "pica8"


@dataclass(frozen=True)
class ProtocolGet:
    title: str
    command: str  # CLI op-mode command (without the `cli -c` wrapper)
    template: str  # template filename under textfsm_templates/pica8/


def _humanize(header: str) -> str:
    """TEXTFSM_VALUE -> "Textfsm Value" for display column headers."""
    return header.replace("_", " ").title()


def parse_table(title: str, template_file: str, text: str) -> ProtocolTable:
    """Run a TextFSM template over ``text`` → a ProtocolTable.

    Rows whose first column is empty are dropped (TextFSM Filldown can emit a
    trailing all-empty row at a section boundary).
    """
    path = _TEMPLATE_DIR / template_file
    with path.open() as fh:
        fsm = textfsm.TextFSM(fh)
    parsed = fsm.ParseText(text)
    columns = tuple(_humanize(h) for h in fsm.header)
    rows = tuple(tuple(str(c) for c in row) for row in parsed if row and str(row[0]).strip())
    return ProtocolTable(title=title, columns=columns, rows=rows)


# Protocol label (as shown in the System tab) -> ordered operational gets.
# Only protocols with proven, parseable CLI output are wired; more are added by
# dropping a template in textfsm_templates/pica8/ and an entry here.
PROTOCOL_GETS: dict[str, tuple[ProtocolGet, ...]] = {
    "OSPF": (
        ProtocolGet("Neighbors", "show ospf neighbor", "show_ospf_neighbor.textfsm"),
        ProtocolGet("Link-state database", "show ospf database", "show_ospf_database.textfsm"),
    ),
    "LLDP": (ProtocolGet("Neighbors", "show lldp neighbor", "show_lldp_neighbor.textfsm"),),
    # PicOS routing is FRR (confirmed via the FRR route-code legend in
    # `show ip route`), so BGP show output is FRR-format. Template authored from
    # FRR docs + unit-tested against the documented sample; pending live confirm
    # on a BGP-running leaf. Route table (`show ip bgp`) deferred — its columns
    # are ragged (blank metric/locprf) and need live samples to parse reliably.
    "BGP": (ProtocolGet("Summary", "show ip bgp summary", "show_ip_bgp_summary.textfsm"),),
}

# Standalone L3 operational gets (not tied to a configured protocol). Surfaced
# as their own pseudo-protocols so the framework stays uniform.
STANDALONE_GETS: dict[str, tuple[ProtocolGet, ...]] = {
    "ARP": (ProtocolGet("ARP table", "show arp", "show_arp.textfsm"),),
}
