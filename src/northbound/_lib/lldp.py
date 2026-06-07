"""LLDP normalization.

LLDP-MIB exposes chassis-IDs and port-IDs as opaque OCTET STRINGs whose
encoding depends on the ``subtype`` companion field. Drivers see wildly
different shapes (puresnmp bytes, eAPI JSON strings, NETCONF text). This
module normalizes everything into the canonical :class:`Neighbor`.

Subtype reference (RFC 4836 / LLDP-MIB):
    chassis_id_subtype:
        1 chassis component, 2 ifAlias, 3 portComponent, 4 MAC address,
        5 networkAddress, 6 interfaceName, 7 local
    port_id_subtype:
        1 ifAlias, 2 portComponent, 3 MAC address, 4 networkAddress,
        5 interfaceName, 6 agentCircuitId, 7 local
"""

from __future__ import annotations

from typing import Any

from northbound.schemas.driver import Neighbor


def _hex_mac(raw: bytes) -> str:
    """Format 6 bytes as a lowercase colon-separated MAC.

    For non-6-byte inputs we fall back to plain hex (still useful to a
    human looking at a log line).
    """
    if len(raw) == 6:
        return ":".join(f"{b:02x}" for b in raw)
    return raw.hex()


def _as_text(raw: bytes | str) -> str:
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    return raw


def normalize_chassis_id(raw: bytes | str, subtype: int | None = None) -> str:
    """Return a canonical chassis-ID string.

    MAC subtype (4) → lowercase colon-MAC. Anything else → decoded text.
    """
    if subtype == 4 and isinstance(raw, bytes):
        return _hex_mac(raw)
    return _as_text(raw).strip().lower() if subtype == 4 else _as_text(raw).strip()


def normalize_port_id(raw: bytes | str, subtype: int | None = None) -> str:
    """Return a canonical port-ID string.

    MAC subtype (3) → lowercase colon-MAC. ifIndex/portComponent (integers)
    → decimal string. Everything else → decoded text.
    """
    if subtype == 3 and isinstance(raw, bytes):
        return _hex_mac(raw)
    if subtype in (2,) and isinstance(raw, bytes):
        # portComponent often comes back as an ASCII decimal
        return _as_text(raw).strip()
    return _strip_quotes(_as_text(raw).strip())


def _strip_quotes(value: str) -> str:
    """Strip matching surrounding single/double quotes.

    Arista eAPI returns the LLDP ``interfaceId`` wrapped in literal double
    quotes (``"Ethernet1"`` — verified live on vEOS), which would otherwise
    leak into the canonical port id. Only strips when both ends match.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def encode_local_port_prefix(local_port: str) -> str:
    """Encode a local-port name as a bracketed prefix for system_description.

    Drivers that lack a dedicated local-port field on :class:`Neighbor` stash
    the local port in the ``system_description`` as ``"[<local_port>] ..."``
    so ``get_neighbors(port=...)`` can filter. Returns ``""`` for an empty
    port (no prefix). Shared by the Cisco and Arista drivers so the encode /
    match pair is identical.
    """
    return f"[{local_port}] " if local_port else ""


def local_port_matches(system_description: str | None, port: str) -> bool:
    """Exact-match a local port against a ``[<local_port>] ...`` prefix.

    Matches the bracketed token EXACTLY — so port ``"Eth1"`` does NOT match a
    description prefixed ``"[Eth1/1] "`` or ``"[Eth10] "``. A plain substring
    test would wrongly match all three.
    """
    if not system_description:
        return False
    return system_description.startswith(f"[{port}] ")


def parse_snmp_lldp_table(rows: list[dict[str, Any]]) -> list[Neighbor]:
    """Build Neighbors from rows of ``lldpRemoteSystemsData`` walk output.

    Expected per-row keys (callers normalize OID column names to these):
        chassis_id, chassis_id_subtype, port_id, port_id_subtype,
        system_name (optional), system_description (optional)
    """
    out: list[Neighbor] = []
    for row in rows:
        chassis = normalize_chassis_id(
            row.get("chassis_id", b""),
            row.get("chassis_id_subtype"),
        )
        port = normalize_port_id(
            row.get("port_id", b""),
            row.get("port_id_subtype"),
        )
        sys_name = row.get("system_name")
        sys_desc = row.get("system_description")
        out.append(
            Neighbor(
                chassis_id=chassis,
                port_id=port,
                system_name=_as_text(sys_name) if sys_name is not None else None,
                system_description=(_as_text(sys_desc) if sys_desc is not None else None),
            )
        )
    return out
