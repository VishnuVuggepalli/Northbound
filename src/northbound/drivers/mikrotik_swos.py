"""MikroTik SwOS driver — READ-ONLY (the switch-only OS, e.g. CSS/CRS in SwOS).

SwOS has no SSH, NETCONF, or RouterOS REST. Its web UI reads small ``.b``
endpoints over HTTP **Digest** auth that return a JS-object-ish text:

    {upt:0x2113aa20,mac:'2cc81b46f40c',brd:'4353...',ver:'322e3138',
     allp:0x03ffffff,temp:0x0000003d, ... }
    {en:0x03ffffff,lnk:0x01202008,spd:[0x07,0x02,...],nm:['506f...','...']}

Quoted values are hex — sometimes hex-ASCII text (brd/id/ver/serial/port names),
sometimes raw bytes (mac); the parser keeps the raw hex and the driver decodes
per field. Numbers are ``0x`` masks/values.

SwOS is read-only forever from Northbound (declared ``writable=False``; the
``assert_writable`` policy blocks any write). This driver surfaces ports
(name, admin/link state, speed), system facts, and the mgmt L3 address.
Grounded against a live CSS326-24G-2S+ on SwOS 2.18.
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

import httpx

from northbound.drivers.base import (
    AuthError,
    Driver,
    DriverError,
    ReachabilityError,
)
from northbound.drivers.registry import register
from northbound.schemas.driver import (
    AuthMethod,
    ConnectionParams,
    Credentials,
    DeviceFacts,
    DiscoveryResult,
    DriverCapabilities,
    L3Interface,
    MacEntry,
    Neighbor,
    PortState,
    ProtocolDetail,
    ProtocolTable,
    SystemInfo,
    TestResult,
    VlanInfo,
)


@register
class MikrotikSwosDriver(Driver):
    """MikroTik SwOS via the ``.b`` HTTP endpoints (Digest auth). Read-only."""

    platform_id = "mikrotik_swos"
    display_name = "MikroTik SwOS"
    capabilities = DriverCapabilities(
        writable=False,  # SwOS is read-only forever from Northbound
        supports_commit_confirm=False,
        native_api_available=True,
        supports_snmp_read=True,
        supports_lldp=False,
        max_concurrency=4,
        auth_methods=[AuthMethod.PASSWORD],
        web_ui_url_template="http://{mgmt_ip}/",
    )

    def __init__(
        self,
        conn: ConnectionParams,
        creds: Credentials,
        *,
        http: Any | None = None,
    ) -> None:
        super().__init__(conn, creds)
        self._http = http  # injected transport (tests); built lazily otherwise

    # ---------- transport ----------

    def _client(self) -> Any:
        # NOTE: deliberately not the shared _lib/transport/HttpxClient — SwOS's
        # `.b` endpoints require HTTP **Digest** auth, which HttpxClient doesn't
        # expose (basic/bearer only). Migration path: add DigestAuth to
        # HttpxClient, then route through it. Until then this builds httpx
        # directly (read-only driver, live-validated against a CSS326).
        if self._http is None:
            scheme = "https" if self._conn.port == 443 else "http"
            base = f"{scheme}://{self._conn.host}" + (
                f":{self._conn.port}" if self._conn.port else ""
            )
            self._http = httpx.AsyncClient(
                base_url=base,
                timeout=self._conn.timeout_seconds,
                verify=False,  # lab switches: self-signed if https at all
                auth=httpx.DigestAuth(self._creds.username or "", self._creds.password or ""),
            )
        return self._http

    async def aclose(self) -> None:
        http, self._http = self._http, None
        if http is not None:
            with contextlib.suppress(Exception):
                await http.aclose()

    async def _fetch(self, endpoint: str) -> str:
        """GET a ``.b`` endpoint → raw text, mapping HTTP errors to the taxonomy."""
        try:
            resp = await self._client().get(f"/{endpoint}")
        except httpx.HTTPError as exc:
            raise ReachabilityError(f"swos: cannot reach {endpoint}: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthError(f"swos: authentication failed ({resp.status_code})")
        if resp.status_code >= 400:
            raise DriverError(f"swos: {endpoint} failed {resp.status_code}")
        return resp.text

    async def _get(self, endpoint: str) -> dict[str, Any]:
        """GET a ``.b`` object endpoint (``{...}``) → dict."""
        return _parse_swos(await self._fetch(endpoint))

    async def _get_array(self, endpoint: str) -> list[dict[str, Any]]:
        """GET a ``.b`` array endpoint (``[{...},{...}]``, e.g. vlan.b) → list of dicts."""
        return _parse_swos_array(await self._fetch(endpoint))

    # ---------- onboarding / read ----------

    async def test_credentials(self) -> TestResult:
        start = time.monotonic()
        try:
            sysb = await self._get("sys.b")
        except (AuthError, ReachabilityError, DriverError) as exc:
            return TestResult(
                ok=False, latency_ms=_ms(start), platform_version=None, error=str(exc)
            )
        ver = f"{_hex_ascii(sysb.get('brd', ''))} SwOS {_hex_ascii(sysb.get('ver', ''))}".strip()
        return TestResult(ok=True, latency_ms=_ms(start), platform_version=ver or None)

    async def reachable(self) -> bool:
        try:
            await self._get("sys.b")
            return True
        except (AuthError, ReachabilityError, DriverError):
            return False

    async def discover(self) -> DiscoveryResult:
        sysb = await self._get("sys.b")
        ports = await self.get_ports()
        running = await self.get_running_config()
        return DiscoveryResult(
            hostname=_hex_ascii(sysb.get("id", "")),
            ports=tuple(ports),
            running_config=running,
            services={"igmp-snooping": bool(int(sysb.get("igmp", 0)))},
        )

    async def get_running_config(self) -> str:
        """SwOS has no text config; synthesize a read-only human summary."""
        sysb = await self._get("sys.b")
        ports = await self.get_ports()
        lines = [
            f"# MikroTik SwOS (read-only) — {_hex_ascii(sysb.get('brd', ''))}",
            f"# identity: {_hex_ascii(sysb.get('id', ''))}",
            f"# version: SwOS {_hex_ascii(sysb.get('ver', ''))}",
            f"# serial: {_hex_ascii(sysb.get('sid', ''))}",
            f"# mgmt-ip: {_le_ip(sysb.get('cip', 0))}",
            "#",
        ]
        for p in ports:
            state = "up" if p.link_up else ("enabled" if p.admin_up else "disabled")
            lines.append(f"{p.name}: {state}" + (f" {p.description}" if p.description else ""))
        return "\n".join(lines) + "\n"

    async def backup_config(self) -> str:
        return await self.get_running_config()

    async def get_ports(self) -> list[PortState]:
        link = await self._get("link.b")
        # fwd.b carries per-port default VLAN (dvid → untagged); vlan.b is the
        # VLAN table (vid + member-port bitmask → tagged). Both are best-effort:
        # a switch with VLANs disabled still returns ports with link/speed only.
        fwd = await self._get("fwd.b")
        vlans = await self._get_array("vlan.b")
        # Per-port RX/TX byte counters (best-effort: a stats read failure must
        # not break the port list).
        stats: dict[str, Any] = {}
        with contextlib.suppress(DriverError):
            stats = await self._get("stats.b")
        return _merge_ports(link, fwd, vlans, stats)

    async def get_neighbors(self, port: str | None = None) -> list[Neighbor]:
        return []  # SwOS exposes no LLDP/neighbor table via the .b endpoints

    async def get_vlans(self) -> list[VlanInfo]:
        """The device VLAN database from vlan.b (vid + member-port count)."""
        out: list[VlanInfo] = []
        for row in await self._get_array("vlan.b"):
            vid = int(row.get("vid", 0) or 0)
            if not vid:
                continue
            out.append(
                VlanInfo(
                    vlan_id=vid,
                    name=_hex_ascii(row.get("nm", "")),
                    port_count=bin(int(row.get("mbr", 0) or 0)).count("1"),
                )
            )
        return out

    async def get_l3_interfaces(self) -> list[L3Interface]:
        sysb = await self._get("sys.b")
        ip = _le_ip(sysb.get("cip", 0))
        if not ip:
            return []
        return [L3Interface(name="management", kind="management", ipv4=ip, enabled=True)]

    async def get_system_info(self) -> SystemInfo:
        sysb = await self._get("sys.b")
        facts = DeviceFacts(
            model=_hex_ascii(sysb.get("brd", "")),
            os_version=f"SwOS {_hex_ascii(sysb.get('ver', ''))}".strip(),
            serial=_hex_ascii(sysb.get("sid", "")),
            base_mac=_hex_mac(sysb.get("mac", "")),
            uptime=_uptime(sysb.get("upt", 0)),
        )

        # L2 host (MAC) table from the dynamic-host endpoint. Each entry is
        # {adr:'<hex mac>', vid:0x<vlan>, prt:0x<port-index>}; prt is a 0-based
        # index into link.b's port list (same numbering as the link/en bitmasks).
        # Verified live against a CSS326-24G-2S+ on SwOS 2.18.
        mac_table: tuple[MacEntry, ...] = ()
        mac_supported = True
        try:
            names = _port_names(await self._get("link.b"))
            hosts = await self._get_array("!dhost.b")
            mac_table = tuple(_host_entry(h, names) for h in hosts if h.get("adr"))
        except DriverError:
            mac_supported = False

        return SystemInfo(facts=facts, mac_table=mac_table, mac_supported=mac_supported)

    async def get_protocol_detail(self, slug: str) -> ProtocolDetail:
        """SwOS is an L2 switch — its only operational tables are the per-port
        statistics. Maps the Diagnostics 'Counters' slug to stats.b (traffic
        counters + RMON packet-size histogram). Routing/ARP/Optics don't apply
        on a pure switch, so they fall through to the empty base result.
        """
        if slug != "Counters":
            return ProtocolDetail(slug=slug)
        try:
            names = _port_names(await self._get("link.b"))
            stats = await self._get("stats.b")
        except DriverError as exc:
            return ProtocolDetail(slug=slug, error=str(exc))
        return ProtocolDetail(
            slug=slug,
            tables=(
                _counters_table(names, stats),
                _errors_table(names, stats),
                _histogram_table(names, stats),
            ),
        )


# ---------------------------------------------------------------------------
# SwOS ``.b`` parser + pure helpers
# ---------------------------------------------------------------------------


def _ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0


def _parse_swos(text: str) -> dict[str, Any]:
    """Parse the SwOS ``{key:val,...}`` body. Quoted values stay raw hex (decoded
    per field by the driver); ``0x`` values become ints; ``[...]`` become lists."""
    body = text.strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    out: dict[str, Any] = {}
    for chunk in _split_top(body):
        key, _, raw = chunk.partition(":")
        out[key.strip()] = _parse_value(raw.strip())
    return out


def _split_top(s: str) -> list[str]:
    """Split on top-level commas, respecting ``[...]`` arrays and ``'...'`` quotes."""
    parts: list[str] = []
    depth = 0
    in_q = False
    buf = ""
    for ch in s:
        if ch == "'":
            in_q = not in_q
            buf += ch
        elif in_q:
            buf += ch
        elif ch == "[":
            depth += 1
            buf += ch
        elif ch == "]":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            if buf.strip():
                parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return parts


def _parse_value(v: str) -> Any:
    if v.startswith("[") and v.endswith("]"):
        return [_parse_scalar(x) for x in _split_array(v[1:-1])]
    return _parse_scalar(v)


def _split_array(inner: str) -> list[str]:
    items: list[str] = []
    in_q = False
    buf = ""
    for ch in inner:
        if ch == "'":
            in_q = not in_q
            buf += ch
        elif ch == "," and not in_q:
            items.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(buf)
    return items


def _parse_scalar(v: str) -> Any:
    v = v.strip()
    if v.startswith("0x"):
        try:
            return int(v, 16)
        except ValueError:
            return 0
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1]  # raw hex — decoded per field
    return v


def _hex_ascii(h: str) -> str:
    """Decode a hex-ASCII SwOS string (e.g. board/identity/port name)."""
    try:
        return bytes.fromhex(h).decode("ascii", "replace").rstrip("\x00")
    except ValueError:
        return h


def _hex_mac(h: str) -> str:
    """Decode 6 raw hex bytes to a colon MAC (e.g. '2cc81b46f40c')."""
    if len(h) == 12:
        return ":".join(h[i : i + 2] for i in range(0, 12, 2))
    return h


def _le_ip(value: int) -> str:
    """SwOS stores the mgmt IP little-endian in a 32-bit int."""
    if not value:
        return ""
    return ".".join(str((value >> (8 * i)) & 0xFF) for i in range(4))


def _uptime(ticks: int) -> str:
    """SwOS uptime is in 1/100s ticks → 'Xd Yh Zm'."""
    secs = ticks // 100
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d {h}h {m}m"


# SwOS link.b ``spd`` per-port code is an INDEX into the speed table, NOT a
# bitmask — confirmed against the SwOS JS:  "10M 100M 1G 10G 5G 2.5G 40G".split.
# So 0=10M, 1=100M, 2=1G, 3=10G, 4=5G, 5=2.5G, 6=40G. A down port reports 7
# (past the table) → unknown. Verified on the live CSS326: linked ports report
# index 2 (1G), and the linked SFP is an "SFP-GE-T" 1000BASE-T module.
_SPD_MBPS: dict[int, int] = {0: 10, 1: 100, 2: 1000, 3: 10000, 4: 5000, 5: 2500, 6: 40000}


def _bit(mask: int, idx: int) -> bool:
    return bool(mask & (1 << idx))


def _parse_swos_array(text: str) -> list[dict[str, Any]]:
    """Parse a SwOS array body ``[{...},{...}]`` (e.g. vlan.b). The objects are
    flat (no nested braces), so each ``{...}`` run is one entry parsed as a dict."""
    return [_parse_swos(obj) for obj in re.findall(r"\{[^{}]*\}", text)]


def _vlan_membership(vlans: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """vlan.b → list of (vid, member-port-bitmask)."""
    out: list[tuple[int, int]] = []
    for row in vlans:
        vid = int(row.get("vid", 0) or 0)
        if vid:
            out.append((vid, int(row.get("mbr", 0) or 0)))
    return out


def _merge_ports(
    link: dict[str, Any],
    fwd: dict[str, Any] | None = None,
    vlans: list[dict[str, Any]] | None = None,
    stats: dict[str, Any] | None = None,
) -> list[PortState]:
    """link.b (+ fwd.b + vlan.b) → PortState list.

    Port count from ``prt``; names from ``nm`` (user labels); admin from ``en``;
    link from ``lnk``; speed from ``spd`` (only when linked). VLANs:
    ``fwd.b.dvid[i]`` is the port's default VLAN → **untagged**; a port is a
    **tagged** member of every vlan.b VLAN whose member-mask includes it, except
    its own default VLAN (standard 802.1Q egress on SwOS — verified on a live
    CSS326: dvid matches the per-port access VLAN encoded in the port names)."""
    count = int(link.get("prt", 0)) or len(link.get("nm", []) or [])
    names = link.get("nm", []) or []
    spd = link.get("spd", []) or []
    en = int(link.get("en", 0))
    lnk = int(link.get("lnk", 0))
    dpx = int(link.get("dpx", 0))

    dvid = (fwd or {}).get("dvid", []) or []
    membership = _vlan_membership(vlans or [])
    has_stats = bool(stats)

    out: list[PortState] = []
    for i in range(count):
        label = _hex_ascii(names[i]) if i < len(names) and isinstance(names[i], str) else ""
        up = _bit(lnk, i)
        speed = _SPD_MBPS.get(int(spd[i])) if up and i < len(spd) else None
        untagged = int(dvid[i]) if i < len(dvid) else None
        tagged = tuple(sorted(vid for vid, mbr in membership if _bit(mbr, i) and vid != untagged))
        out.append(
            PortState(
                name=label or f"Port{i + 1}",
                admin_up=_bit(en, i),
                link_up=up,
                speed_mbps=speed,
                duplex="full" if up and _bit(dpx, i) else None,
                mac=None,
                mtu=None,
                untagged_vlan=untagged,
                tagged_vlans=tagged,
                description=label,
                host_model="",
                bmc_ip="",
                notes="",
                services={},
                rx_bytes=_stat_lo_hi(stats or {}, "rb", "rbh", i) if has_stats else None,
                tx_bytes=_stat_lo_hi(stats or {}, "tb", "tbh", i) if has_stats else None,
            )
        )
    return out


def _port_names(link: dict[str, Any]) -> list[str]:
    """Decode link.b's ``nm`` (hex-ASCII user labels) into a port-indexed list."""
    return [_hex_ascii(n) if isinstance(n, str) else "" for n in (link.get("nm") or [])]


def _host_entry(row: dict[str, Any], names: list[str]) -> MacEntry:
    """One !dhost.b row → MacEntry. ``adr`` is a bare-hex MAC, ``vid`` the VLAN
    (0 → none), ``prt`` a 0-based port index into ``names``. The endpoint is the
    dynamic (learned) table, so every entry is Dynamic; SwOS carries no age."""
    prt = int(row.get("prt", 0) or 0)
    vid = int(row.get("vid", 0) or 0)
    name = names[prt] if 0 <= prt < len(names) else ""
    return MacEntry(
        vlan=vid or None,
        mac=_hex_mac(str(row.get("adr", ""))),
        interface=name or f"Port{prt + 1}",
        type="Dynamic",
        age=None,
    )


def _stat_lo_hi(stats: dict[str, Any], lo_key: str, hi_key: str, i: int) -> int:
    """Combine a SwOS 64-bit counter split across low/high 32-bit arrays:
    ``(high << 32) | low``. Verified pairing (rb/rbh, tb/tbh) on a live CSS326."""
    lo = stats.get(lo_key) or []
    hi = stats.get(hi_key) or []
    val = int(lo[i]) if i < len(lo) else 0
    if i < len(hi):
        val |= int(hi[i]) << 32
    return val


def _stat(stats: dict[str, Any], key: str, i: int) -> int:
    arr = stats.get(key) or []
    return int(arr[i]) if i < len(arr) else 0


def _human_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{int(f)} B" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def _counters_table(names: list[str], stats: dict[str, Any]) -> ProtocolTable:
    """stats.b → per-port traffic counters. Bytes are 64-bit (low/high pair);
    rtp/ttp are RX/TX total packets — verified on a live CSS326 to equal the
    sum of unicast+broadcast+multicast packet counters."""
    rows = tuple(
        (
            names[i] or f"Port{i + 1}",
            _human_bytes(_stat_lo_hi(stats, "rb", "rbh", i)),
            _human_bytes(_stat_lo_hi(stats, "tb", "tbh", i)),
            str(_stat(stats, "rtp", i)),
            str(_stat(stats, "ttp", i)),
        )
        for i in range(len(names))
    )
    return ProtocolTable(
        title="Port counters",
        columns=("Port", "RX", "TX", "RX pkts", "TX pkts"),
        rows=rows,
    )


def _errors_table(names: list[str], stats: dict[str, Any]) -> ProtocolTable:
    """stats.b error counters. Keys are doc-derived (RMON/EtherLike naming) and
    confirmed present on a live CSS326: rfcs=RX FCS, rae=RX align, rov=RX
    overflow, fr=RX fragments, tcl=TX collisions. A healthy link reads all-zero."""
    cols = ("Port", "RX FCS", "RX align", "RX overflow", "RX fragments", "TX coll")
    keys = ("rfcs", "rae", "rov", "fr", "tcl")
    rows = tuple(
        (names[i] or f"Port{i + 1}", *(str(_stat(stats, k, i)) for k in keys))
        for i in range(len(names))
    )
    return ProtocolTable(title="Errors", columns=cols, rows=rows)


def _histogram_table(names: list[str], stats: dict[str, Any]) -> ProtocolTable:
    """stats.b RMON packet-size histogram (p64..p1k buckets) per port."""
    keys = ("p64", "p65", "p128", "p256", "p512", "p1k")
    rows = tuple(
        (names[i] or f"Port{i + 1}", *(str(_stat(stats, k, i)) for k in keys))
        for i in range(len(names))
    )
    return ProtocolTable(
        title="Packet-size histogram",
        columns=("Port", "64", "65-127", "128-255", "256-511", "512-1023", "1024+"),
        rows=rows,
    )
